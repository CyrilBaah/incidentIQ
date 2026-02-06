#!/usr/bin/env python3
"""
Generate 7 days of baseline data for IncidentIQ

Usage:
    python data/generate_baselines.py                    # Generate 7 days
    python data/generate_baselines.py --days 14          # Generate 14 days
    python data/generate_baselines.py --dry-run          # Preview only
    python data/generate_baselines.py --services 3       # Only 3 services
"""

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Service configurations with realistic characteristics
SERVICES_CONFIG = {
    "api-gateway": {
        "requests_per_minute": 10000,
        "response_time_mean": 150,
        "response_time_stddev": 30,
        "error_messages": {
            "INFO": [
                "Request processed successfully",
                "Routing to downstream service",
                "Authentication successful",
                "Request validated",
                "Cache hit for user session"
            ],
            "WARN": [
                "Rate limit approaching for client",
                "Slow response from auth-service",
                "Circuit breaker warning",
                "High memory usage detected",
                "Connection pool utilization high"
            ],
            "ERROR": [
                "Gateway timeout from downstream",
                "Authentication service unavailable",
                "Request validation failed",
                "Circuit breaker open",
                "Load balancer error"
            ],
            "CRITICAL": [
                "All downstream services unreachable",
                "Authentication service down",
                "Critical memory leak detected",
                "Database connection pool exhausted",
                "Security breach attempt detected"
            ]
        },
        "error_types": ["GatewayTimeoutException", "AuthenticationException", "ValidationException", "CircuitBreakerException"]
    },
    "auth-service": {
        "requests_per_minute": 2000,
        "response_time_mean": 80,
        "response_time_stddev": 20,
        "error_messages": {
            "INFO": [
                "User authenticated successfully",
                "Token generated and cached",
                "Session validated",
                "Password reset email sent",
                "Multi-factor authentication completed"
            ],
            "WARN": [
                "Multiple login attempts detected",
                "Token refresh needed",
                "Suspicious login pattern",
                "Session cleanup required",
                "Rate limiting applied"
            ],
            "ERROR": [
                "Invalid credentials provided",
                "Token validation failed",
                "User account locked",
                "LDAP connection failed",
                "Session store unreachable"
            ],
            "CRITICAL": [
                "Authentication service database down",
                "Certificate expired",
                "Security token compromised",
                "LDAP service unavailable",
                "Critical auth cache failure"
            ]
        },
        "error_types": ["AuthenticationException", "TokenValidationException", "AccountLockedException", "LDAPException"]
    },
    "payment-service": {
        "requests_per_minute": 500,
        "response_time_mean": 300,
        "response_time_stddev": 50,
        "error_messages": {
            "INFO": [
                "Payment processed successfully",
                "Card validated and authorized",
                "Refund completed",
                "Payment webhook delivered",
                "Transaction recorded"
            ],
            "WARN": [
                "Payment gateway latency high",
                "Fraud detection triggered",
                "Currency conversion applied",
                "Retry attempt for failed payment",
                "Merchant account limit warning"
            ],
            "ERROR": [
                "Credit card declined",
                "Payment gateway timeout",
                "Insufficient funds",
                "Fraud detection blocked payment",
                "Payment processor unavailable"
            ],
            "CRITICAL": [
                "Payment gateway completely down",
                "Critical fraud pattern detected",
                "Payment processor security breach",
                "Database transaction rollback failed",
                "PCI compliance violation"
            ]
        },
        "error_types": ["PaymentDeclinedException", "FraudException", "PaymentGatewayException", "PCIViolationException"]
    },
    "notification-service": {
        "requests_per_minute": 1000,
        "response_time_mean": 200,
        "response_time_stddev": 40,
        "error_messages": {
            "INFO": [
                "Email notification sent successfully",
                "SMS delivered to recipient",
                "Push notification queued",
                "Template rendered correctly",
                "Webhook notification posted"
            ],
            "WARN": [
                "Email delivery delayed",
                "SMS rate limit reached",
                "Push notification retry scheduled",
                "Template rendering slow",
                "Webhook endpoint slow response"
            ],
            "ERROR": [
                "Email delivery failed",
                "SMS service unavailable",
                "Push notification rejected",
                "Template rendering failed",
                "Webhook endpoint unreachable"
            ],
            "CRITICAL": [
                "Email service completely down",
                "SMS provider outage",
                "Push notification service critical error",
                "Template service database corruption",
                "Critical webhook security failure"
            ]
        },
        "error_types": ["EmailDeliveryException", "SMSException", "PushNotificationException", "TemplateException"]
    },
    "user-service": {
        "requests_per_minute": 3000,
        "response_time_mean": 100,
        "response_time_stddev": 25,
        "error_messages": {
            "INFO": [
                "User profile updated successfully",
                "User registration completed",
                "Profile data retrieved",
                "User preferences saved",
                "Account verification completed"
            ],
            "WARN": [
                "User profile validation warning",
                "Duplicate email detected",
                "Profile update rate limit",
                "Database query optimization needed",
                "Cache miss for user data"
            ],
            "ERROR": [
                "User not found",
                "Profile update validation failed",
                "Database constraint violation",
                "User service database timeout",
                "Profile image upload failed"
            ],
            "CRITICAL": [
                "User database completely down",
                "Critical user data corruption",
                "User service security breach",
                "Profile service crash",
                "Critical data consistency error"
            ]
        },
        "error_types": ["UserNotFoundException", "ValidationException", "DatabaseException", "SecurityException"]
    }
}

# HTTP status code distributions
HTTP_STATUS_WEIGHTS = {
    200: 0.90,
    201: 0.03,
    400: 0.02,
    404: 0.02,
    500: 0.02,
    503: 0.01
}

# Log level distributions
LOG_LEVEL_WEIGHTS = {
    "INFO": 0.92,
    "WARN": 0.05,
    "ERROR": 0.025,
    "CRITICAL": 0.005
}

class BaselineDataGenerator:
    def __init__(self, es_client: Elasticsearch, days: int = 7, services: List[str] = None):
        self.es = es_client
        self.days = days
        self.services = services or list(SERVICES_CONFIG.keys())
        self.start_time = datetime.utcnow() - timedelta(days=days)
        
    def get_business_hour_multiplier(self, timestamp: datetime) -> float:
        """Calculate traffic multiplier based on time of day and day of week"""
        hour = timestamp.hour
        weekday = timestamp.weekday()
        
        # Weekend reduction (Saturday=5, Sunday=6)
        weekend_factor = 0.5 if weekday >= 5 else 1.0
        
        # Business hours (9-17) have higher traffic
        if 9 <= hour <= 17:
            business_factor = 2.0
        elif 6 <= hour <= 9 or 17 <= hour <= 22:
            business_factor = 1.5  # Shoulder hours
        else:
            business_factor = 0.8  # Night hours
            
        return weekend_factor * business_factor
    
    def generate_log_message(self, service: str, level: str) -> Tuple[str, str]:
        """Generate realistic log message and error type"""
        config = SERVICES_CONFIG[service]
        message = random.choice(config["error_messages"][level])
        
        error_type = None
        if level in ["ERROR", "CRITICAL"]:
            error_type = random.choice(config["error_types"])
            
        return message, error_type
    
    def generate_log_entry(self, timestamp: datetime, service: str) -> Dict:
        """Generate a single log entry"""
        level = np.random.choice(
            list(LOG_LEVEL_WEIGHTS.keys()),
            p=list(LOG_LEVEL_WEIGHTS.values())
        )
        
        http_status = np.random.choice(
            list(HTTP_STATUS_WEIGHTS.keys()),
            p=list(HTTP_STATUS_WEIGHTS.values())
        )
        
        message, error_type = self.generate_log_message(service, level)
        
        config = SERVICES_CONFIG[service]
        response_time = max(0, np.random.normal(
            config["response_time_mean"],
            config["response_time_stddev"]
        ))
        
        # Add correlation: if one service has errors, others slightly affected
        if level in ["ERROR", "CRITICAL"]:
            response_time *= random.uniform(1.5, 3.0)  # Errors cause slower responses
        
        entry = {
            "@timestamp": timestamp.isoformat() + "Z",
            "service": service,
            "environment": "production",
            "level": level,
            "message": message,
            "http_status": http_status,
            "response_time": round(response_time, 2),
            "request_id": str(uuid.uuid4()),
            "host": {
                "name": f"{service}-pod-{random.randint(1, 3)}"
            }
        }
        
        if error_type:
            entry["error_type"] = error_type
            
        return entry
    
    def generate_metric_entry(self, timestamp: datetime, service: str, memory_base: float) -> Dict:
        """Generate a single metrics entry"""
        business_multiplier = self.get_business_hour_multiplier(timestamp)
        
        # CPU with business hour variation
        base_cpu = 40.0
        cpu_variation = business_multiplier * 15.0  # Higher CPU during busy times
        cpu_percent = max(0, min(100, np.random.normal(
            base_cpu + cpu_variation, 8.0
        )))
        
        # Memory with slow drift over time
        days_elapsed = (timestamp - self.start_time).total_seconds() / (24 * 3600)
        memory_drift = days_elapsed * 2.0  # 2% drift per day
        memory_percent = max(0, min(95, np.random.normal(
            memory_base + memory_drift, 10.0
        )))
        
        # Request count based on service configuration and business hours
        base_requests = SERVICES_CONFIG[service]["requests_per_minute"] / 4  # 15-second intervals
        request_count = max(0, np.random.poisson(base_requests * business_multiplier))
        
        # Error count correlated with log errors (approximately)
        error_rate = LOG_LEVEL_WEIGHTS["ERROR"] + LOG_LEVEL_WEIGHTS["CRITICAL"]
        error_count = np.random.poisson(request_count * error_rate)
        
        # Database connection pool
        db_pool_active = random.randint(10, 30)
        db_pool_idle = 50 - db_pool_active
        
        # Cache hit rate (varies slightly)
        cache_hit_rate = random.uniform(0.80, 0.95)
        
        # Response time percentiles based on service config
        config = SERVICES_CONFIG[service]
        p50_latency = max(0, np.random.normal(config["response_time_mean"] * 0.8, 15))
        p95_latency = max(0, np.random.normal(config["response_time_mean"] * 1.3, 20))
        p99_latency = max(0, np.random.normal(config["response_time_mean"] * 2.0, 30))
        
        return {
            "@timestamp": timestamp.isoformat() + "Z",
            "service": service,
            "environment": "production",
            "cpu_percent": round(cpu_percent, 2),
            "memory_percent": round(memory_percent, 2),
            "request_count": request_count,
            "error_count": error_count,
            "request_latency_p50": round(p50_latency, 2),
            "request_latency_p95": round(p95_latency, 2),
            "request_latency_p99": round(p99_latency, 2),
            "db_connection_pool_active": db_pool_active,
            "db_connection_pool_idle": db_pool_idle,
            "cache_hit_rate": round(cache_hit_rate, 3),
            "host": {
                "name": f"{service}-pod-{random.randint(1, 3)}"
            }
        }
    
    def generate_logs(self, dry_run: bool = False) -> int:
        """Generate log entries for all services"""
        total_docs = 0
        current_time = self.start_time
        end_time = datetime.utcnow()
        
        # Calculate total iterations for progress bar
        time_intervals = int((end_time - current_time).total_seconds() / 5)  # 5-second intervals
        total_iterations = time_intervals * len(self.services)
        
        print(f"🔍 Generating logs for {len(self.services)} services over {self.days} days...")
        
        batch = []
        batch_size = 1000
        
        with tqdm(total=total_iterations, desc="Generating logs") as pbar:
            while current_time < end_time:
                for service in self.services:
                    # Generate logs based on service volume and time patterns
                    business_multiplier = self.get_business_hour_multiplier(current_time)
                    base_logs_per_interval = 10  # Base logs per 5-second interval
                    logs_count = max(1, int(np.random.poisson(base_logs_per_interval * business_multiplier)))
                    
                    for _ in range(logs_count):
                        log_entry = self.generate_log_entry(current_time, service)
                        total_docs += 1
                        
                        if not dry_run:
                            batch.append({
                                "_op_type": "create",
                                "_index": f"logs-app-{current_time.strftime('%Y.%m.%d')}",
                                "_source": log_entry
                            })
                        
                    # Bulk insert when batch is full
                    if not dry_run and len(batch) >= batch_size:
                        try:
                            success, errors = helpers.bulk(self.es, batch, raise_on_error=False)
                            if errors:
                                print(f"\n⚠️  {len(errors)} documents failed to index")
                                if errors:
                                    print(f"First error: {errors[0]}")
                        except Exception as e:
                            print(f"\n⚠️  Bulk insert error: {e}")
                        batch = []
                    
                    pbar.update(1)
                
                current_time += timedelta(seconds=5)
        
        # Insert remaining documents
        if not dry_run and batch:
            helpers.bulk(self.es, batch)
            
        return total_docs
    
    def generate_metrics(self, dry_run: bool = False) -> int:
        """Generate metrics entries for all services"""
        total_docs = 0
        current_time = self.start_time
        end_time = datetime.utcnow()
        
        # Calculate total iterations for progress bar
        time_intervals = int((end_time - current_time).total_seconds() / 15)  # 15-second intervals
        total_iterations = time_intervals * len(self.services)
        
        print(f"📊 Generating metrics for {len(self.services)} services over {self.days} days...")
        
        batch = []
        batch_size = 1000
        
        # Initialize memory baseline per service
        memory_baselines = {service: random.uniform(55, 65) for service in self.services}
        
        with tqdm(total=total_iterations, desc="Generating metrics") as pbar:
            while current_time < end_time:
                for service in self.services:
                    metric_entry = self.generate_metric_entry(
                        current_time, 
                        service, 
                        memory_baselines[service]
                    )
                    total_docs += 1
                    
                    if not dry_run:
                        batch.append({
                            "_op_type": "create",
                            "_index": f"metrics-system-{current_time.strftime('%Y.%m.%d')}",
                            "_source": metric_entry
                        })
                    
                    # Bulk insert when batch is full
                    if not dry_run and len(batch) >= batch_size:
                        try:
                            success, errors = helpers.bulk(self.es, batch, raise_on_error=False)
                            if errors:
                                print(f"\n⚠️  {len(errors)} metric documents failed to index")
                        except Exception as e:
                            print(f"\n⚠️  Metrics bulk insert error: {e}")
                        batch = []
                    
                    pbar.update(1)
                
                current_time += timedelta(seconds=15)
        
        # Insert remaining documents
        if not dry_run and batch:
            try:
                success, errors = helpers.bulk(self.es, batch, raise_on_error=False)
                if errors:
                    print(f"\n⚠️  {len(errors)} metric documents in final batch failed")
            except Exception as e:
                print(f"\n⚠️  Final metrics bulk insert error: {e}")
            
        return total_docs

def setup_elasticsearch() -> Elasticsearch:
    """Setup Elasticsearch connection"""
    es_config = {}
    
    # Cloud configuration
    if os.getenv("ELASTIC_CLOUD_ID"):
        es_config["cloud_id"] = os.getenv("ELASTIC_CLOUD_ID")
        if os.getenv("ELASTIC_API_KEY"):
            es_config["api_key"] = os.getenv("ELASTIC_API_KEY")
        elif os.getenv("ELASTIC_PASSWORD"):
            es_config["basic_auth"] = ("elastic", os.getenv("ELASTIC_PASSWORD"))
    else:
        # Local configuration
        es_config["hosts"] = [os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")]
        if os.getenv("ELASTIC_PASSWORD"):
            es_config["basic_auth"] = ("elastic", os.getenv("ELASTIC_PASSWORD"))
    
    return Elasticsearch(**es_config)

def main():
    parser = argparse.ArgumentParser(description="Generate baseline data for IncidentIQ")
    parser.add_argument("--days", type=int, default=7, help="Number of days of data to generate")
    parser.add_argument("--dry-run", action="store_true", help="Preview without inserting data")
    parser.add_argument("--services", type=int, help="Number of services to generate (default: all 5)")
    
    args = parser.parse_args()
    
    print("🚀 IncidentIQ Baseline Data Generator")
    print("=" * 50)
    
    # Setup Elasticsearch
    try:
        es = setup_elasticsearch()
        es.info()  # Test connection
        print("✅ Connected to Elasticsearch")
    except Exception as e:
        print(f"❌ Failed to connect to Elasticsearch: {e}")
        return 1
    
    # Configure services
    services = list(SERVICES_CONFIG.keys())
    if args.services:
        services = services[:args.services]
    
    print(f"📋 Configuration:")
    print(f"   • Days of data: {args.days}")
    print(f"   • Services: {len(services)} ({', '.join(services)})")
    print(f"   • Dry run: {'Yes' if args.dry_run else 'No'}")
    print()
    
    # Generate data
    generator = BaselineDataGenerator(es, days=args.days, services=services)
    
    start_time = datetime.utcnow()
    
    # Generate logs
    log_count = generator.generate_logs(dry_run=args.dry_run)
    print(f"✅ Generated {log_count:,} log entries")
    
    # Generate metrics
    metric_count = generator.generate_metrics(dry_run=args.dry_run)
    print(f"✅ Generated {metric_count:,} metric entries")
    
    elapsed = datetime.utcnow() - start_time
    total_docs = log_count + metric_count
    
    print()
    print("📈 Summary:")
    print(f"   • Total documents: {total_docs:,}")
    print(f"   • Execution time: {elapsed.total_seconds():.1f} seconds")
    print(f"   • Documents/second: {total_docs / elapsed.total_seconds():.0f}")
    
    if args.dry_run:
        print("   • This was a dry run - no data was inserted")
    else:
        print("   • Data successfully inserted into Elasticsearch")
    
    print()
    print("🎯 Next steps:")
    print("   1. Run your ES|QL baseline calculation queries")
    print("   2. Verify data quality in Kibana")
    print("   3. Generate incident simulation data")
    
    return 0

if __name__ == "__main__":
    exit(main())