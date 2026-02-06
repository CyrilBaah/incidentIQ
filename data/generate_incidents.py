#!/usr/bin/env python3
"""
Generate historical incidents for IncidentIQ

Usage:
    python data/generate_incidents.py                  # Generate 25 incidents
    python data/generate_incidents.py --count 50       # Generate 50 incidents
    python data/generate_incidents.py --dry-run        # Preview only
"""

import argparse
import hashlib
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import numpy as np
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers
from tqdm import tqdm

# Optional sentence transformer for embeddings
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_MODEL_AVAILABLE = True
except ImportError:
    SENTENCE_MODEL_AVAILABLE = False
    print("⚠️  sentence_transformers not installed. Embeddings will be skipped.")
    print("   Install with: pip install sentence-transformers")

# Load environment variables
load_dotenv()

# Incident templates with realistic variations
INCIDENT_TEMPLATES = {
    "database_pool_exhaustion": {
        "frequency": 4,  # Occurs 3-4 times
        "services": ["api-gateway", "payment-service", "user-service"],
        "error_type": "DatabaseTimeoutException",
        "error_messages": [
            "Database connection timeout after 30s wait",
            "Connection pool exhausted: 50/50 connections active",
            "Unable to acquire database connection within timeout",
            "Database connection pool depleted - all connections in use",
            "Timeout waiting for available database connection"
        ],
        "symptoms": "Error rate spike from 2% to 85%, latency increased from 150ms to 5000ms",
        "root_causes": [
            "Connection pool size (50) insufficient for current traffic load",
            "Database connection leak preventing pool cleanup",
            "Traffic spike overwhelmed available connection pool",
            "Long-running queries blocking connection pool"
        ],
        "resolution_steps": [
            "1. Monitor connection pool metrics\n2. Restart affected service pods\n3. Verify connection pool reset\n4. Monitor error rates return to normal",
            "1. Identify connection pool exhaustion\n2. Rolling restart of service instances\n3. Increase connection pool monitoring\n4. Validate service recovery",
            "1. Check database connection pool status\n2. Perform emergency service restart\n3. Verify database connectivity restored\n4. Monitor application metrics"
        ],
        "resolution_workflow": "safe_service_restart",
        "resolution_time_range": (6*60, 10*60),  # 6-10 minutes
        "resolution_confidence_range": (0.93, 0.98),
        "severity_weights": {"CRITICAL": 0.6, "HIGH": 0.4},
        "auto_resolved_chance": 0.7,
        "tags": ["database", "connection_pool", "timeout", "restart"]
    },
    "memory_leak": {
        "frequency": 3,  # Occurs 2-3 times
        "services": ["notification-service", "user-service", "auth-service"],
        "error_type": "OutOfMemoryError", 
        "error_messages": [
            "Java heap space exhausted - OutOfMemoryError",
            "Container killed by OOMKiller: memory limit exceeded",
            "GC overhead limit exceeded - heap dump generated",
            "Native memory allocation failed - insufficient memory",
            "Process terminated due to memory pressure"
        ],
        "symptoms": "Gradual memory increase over 6-8 hours, then service crash and restart loop",
        "root_causes": [
            "Memory leak in background image processing task",
            "Unclosed file handles accumulating over time", 
            "Cache growing unbounded without eviction policy",
            "Thread pool creating excessive threads without cleanup"
        ],
        "resolution_steps": [
            "1. Identify memory leak via heap dump analysis\n2. Deploy hotfix version v2.1.3\n3. Monitor memory usage post-deployment\n4. Verify no memory growth over 24 hours",
            "1. Collect heap dump before restart\n2. Apply memory leak patch\n3. Redeploy with updated container limits\n4. Establish memory monitoring alerts",
            "1. Analyze memory growth patterns\n2. Implement fix for resource cleanup\n3. Deploy patched version\n4. Verify memory stability"
        ],
        "resolution_workflow": "deploy_hotfix",
        "resolution_time_range": (45*60, 90*60),  # 45-90 minutes
        "resolution_confidence_range": (0.85, 0.92),
        "severity_weights": {"CRITICAL": 0.7, "HIGH": 0.3},
        "auto_resolved_chance": 0.3,
        "tags": ["memory_leak", "oom", "deployment", "hotfix"]
    },
    "external_api_failure": {
        "frequency": 5,  # Occurs 4-5 times
        "services": ["payment-service", "notification-service", "auth-service"],
        "error_type": "ExternalServiceException",
        "error_messages": [
            "Payment gateway API returned 503 Service Unavailable",
            "SMTP service connection refused - external provider down",
            "OAuth provider unreachable - authentication failing",
            "Third-party API timeout after 30 seconds",
            "External webhook delivery failed - endpoint unreachable"
        ],
        "symptoms": "500 errors when calling external service, fallback mechanisms not triggered",
        "root_causes": [
            "Stripe payment API experiencing regional outage",
            "SendGrid email service maintenance window",
            "Auth0 identity provider network connectivity issues", 
            "External API rate limiting our service requests",
            "DNS resolution failure for external service endpoints"
        ],
        "resolution_steps": [
            "1. Confirm external API status via status page\n2. Enable circuit breaker and fallback logic\n3. Monitor for service recovery\n4. Disable fallback once primary API restored",
            "1. Validate external service outage\n2. Activate backup service provider\n3. Update DNS routing temporarily\n4. Revert to primary once available",
            "1. Check external service health\n2. Implement retry mechanism with exponential backoff\n3. Wait for service provider recovery\n4. Resume normal operations"
        ],
        "resolution_workflow": "enable_fallback", 
        "resolution_time_range": (20*60, 60*60),  # 20-60 minutes
        "resolution_confidence_range": (0.88, 0.95),
        "severity_weights": {"HIGH": 0.5, "MEDIUM": 0.4, "CRITICAL": 0.1},
        "auto_resolved_chance": 0.6,
        "tags": ["external_api", "third_party", "fallback", "circuit_breaker"]
    },
    "cache_invalidation": {
        "frequency": 3,  # Occurs 2-3 times
        "services": ["auth-service", "api-gateway", "user-service"],
        "error_type": "StaleDataException",
        "error_messages": [
            "Cache invalidation failed - users seeing outdated session data",
            "Redis cache inconsistency detected across cluster nodes",
            "User permissions cache not updating after role changes",
            "API response cache serving stale data after configuration update",
            "Session cache corruption - authentication state inconsistent"
        ],
        "symptoms": "Users see outdated data, cache hit rate drops from 90% to 45%", 
        "root_causes": [
            "Redis cluster split-brain causing cache inconsistency",
            "Cache invalidation events not propagating to all nodes",
            "Race condition in cache update mechanism",
            "Cache key namespace collision causing incorrect evictions"
        ],
        "resolution_steps": [
            "1. Identify cache inconsistency scope\n2. Flush affected cache regions\n3. Restart cache cluster nodes\n4. Verify cache consistency restored",
            "1. Clear all cache entries for affected service\n2. Restart application to rebuild cache\n3. Monitor cache hit rates recovery\n4. Implement better cache validation",
            "1. Manual cache flush via admin interface\n2. Rolling restart of cache nodes\n3. Verify data consistency\n4. Update cache invalidation logic"
        ],
        "resolution_workflow": "clear_cache_restart",
        "resolution_time_range": (5*60, 8*60),  # 5-8 minutes
        "resolution_confidence_range": (0.88, 0.95),
        "severity_weights": {"HIGH": 0.4, "MEDIUM": 0.6},
        "auto_resolved_chance": 0.8,
        "tags": ["cache", "redis", "stale_data", "invalidation"]
    },
    "disk_space_full": {
        "frequency": 2,  # Occurs 1-2 times
        "services": ["api-gateway", "notification-service", "user-service", "auth-service"],
        "error_type": "DiskFullException",
        "error_messages": [
            "No space left on device - unable to write log files", 
            "Disk usage at 100% - write operations failing",
            "Database unable to write WAL files - disk full",
            "Temporary file creation failed - insufficient disk space",
            "Log rotation failed - disk space exhausted"
        ],
        "symptoms": "Write operations failing, service degradation, log files not rotating",
        "root_causes": [
            "Application logs not being rotated properly, filling disk",
            "Database transaction logs accumulating without cleanup", 
            "Temporary files from failed operations not cleaned up",
            "Kubernetes persistent volume size insufficient for workload"
        ],
        "resolution_steps": [
            "1. Identify disk usage by directory\n2. Clear old log files older than 7 days\n3. Increase PVC size from 10GB to 20GB\n4. Implement automatic log cleanup policy",
            "1. Emergency cleanup of /tmp and /var/log directories\n2. Restart affected services\n3. Resize persistent volume\n4. Configure log retention policies",
            "1. Free disk space by removing old files\n2. Resize underlying storage\n3. Restart services to clear errors\n4. Monitor disk usage going forward"
        ],
        "resolution_workflow": "manual_fix",
        "resolution_time_range": (15*60, 30*60),  # 15-30 minutes
        "resolution_confidence_range": (0.95, 0.99),
        "severity_weights": {"CRITICAL": 0.5, "HIGH": 0.5},
        "auto_resolved_chance": 0.2,
        "tags": ["disk_space", "storage", "cleanup", "volume"]
    },
    "rate_limiting": {
        "frequency": 4,  # Occurs 3-4 times
        "services": ["api-gateway"],
        "error_type": "RateLimitExceededException", 
        "error_messages": [
            "Rate limit exceeded: 1000 requests/minute threshold breached",
            "Too many requests from client - rate limiting activated",
            "API quota exhausted - blocking requests for cooldown period",
            "Request frequency exceeds allowed rate - returning 429 status",
            "Client rate limit triggered - implement exponential backoff"
        ],
        "symptoms": "429 Too Many Requests errors, legitimate requests being rejected",
        "root_causes": [
            "DDoS attack overwhelming API gateway with requests",
            "Mobile app bug causing infinite retry loop",
            "Partner integration misconfigured with aggressive retry",
            "Rate limit threshold set too low for legitimate traffic patterns"
        ],
        "resolution_steps": [
            "1. Analyze request patterns to identify source\n2. Temporarily increase rate limit to 2000/min\n3. Block suspicious IP addresses\n4. Contact client to fix retry logic",
            "1. Identify traffic spike source via logs\n2. Implement temporary rate limit bypass for known clients\n3. Add IP-based rate limiting rules\n4. Restore normal limits once traffic normalizes",
            "1. Emergency rate limit increase\n2. Whitelist legitimate client IPs\n3. Investigate traffic anomaly\n4. Implement adaptive rate limiting"
        ],
        "resolution_workflow": "adjust_rate_limits",
        "resolution_time_range": (3*60, 5*60),  # 3-5 minutes
        "resolution_confidence_range": (0.82, 0.90),
        "severity_weights": {"HIGH": 0.4, "MEDIUM": 0.6},
        "auto_resolved_chance": 0.9,
        "tags": ["rate_limiting", "ddos", "throttling", "429"]
    },
    "configuration_error": {
        "frequency": 3,  # Occurs 2-3 times
        "services": ["payment-service", "auth-service", "notification-service"],
        "error_type": "ConfigurationException",
        "error_messages": [
            "Service failed to start: invalid database connection string",
            "Configuration validation failed: missing required environment variable",
            "Unable to parse configuration file: invalid JSON format",
            "Service startup failed: SSL certificate path not found",
            "Environment variable API_KEY not set - service cannot initialize"
        ],
        "symptoms": "Service fails to start after deployment, health checks failing",
        "root_causes": [
            "Database URL updated in production but not in configuration",
            "Environment variable removed from deployment manifest",
            "Configuration file corrupted during deployment process", 
            "SSL certificate expired and not renewed in time"
        ],
        "resolution_steps": [
            "1. Identify configuration error from startup logs\n2. Rollback to previous working version v2.3.1\n3. Verify service starts correctly\n4. Fix configuration and redeploy",
            "1. Check deployment diff for configuration changes\n2. Emergency rollback deployment\n3. Update configuration with correct values\n4. Deploy fixed version",
            "1. Validate service configuration\n2. Revert to last known good deployment\n3. Correct configuration values\n4. Test and redeploy"
        ],
        "resolution_workflow": "rollback_deployment",
        "resolution_time_range": (10*60, 20*60),  # 10-20 minutes
        "resolution_confidence_range": (0.90, 0.96),
        "severity_weights": {"CRITICAL": 0.3, "HIGH": 0.7},
        "auto_resolved_chance": 0.5,
        "tags": ["configuration", "deployment", "rollback", "env_vars"]
    }
}

class IncidentGenerator:
    def __init__(self, es_client: Elasticsearch, count: int = 25):
        self.es = es_client
        self.count = count
        self.end_time = datetime.utcnow()
        self.start_time = self.end_time - timedelta(days=90)
        
        # Initialize sentence transformer for embeddings (optional)
        if SENTENCE_MODEL_AVAILABLE:
            print("🤖 Loading sentence transformer model...")
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        else:
            self.embedding_model = None
        
    def generate_error_signature(self, service: str, error_type: str) -> str:
        """Generate consistent error signature hash"""
        signature_input = f"{service}:{error_type}"
        return hashlib.md5(signature_input.encode()).hexdigest()[:8]
    
    def generate_embedding(self, error_message: str) -> Optional[List[float]]:
        """Generate 384-dim embedding for error message"""
        if self.embedding_model is None:
            # Return None if model not available
            return None
        embedding = self.embedding_model.encode(error_message)
        return embedding.tolist()
    
    def select_incidents_to_generate(self) -> List[Tuple[str, Dict]]:
        """Select which incidents to generate based on frequencies"""
        incidents_to_generate = []
        
        for template_name, template in INCIDENT_TEMPLATES.items():
            # Generate the specified frequency, with some variation
            count = template["frequency"]
            if self.count < 25:
                # Scale down for smaller counts
                count = max(1, int(count * (self.count / 25)))
            elif self.count > 25:
                # Scale up for larger counts
                count = int(count * (self.count / 25))
            
            for _ in range(count):
                incidents_to_generate.append((template_name, template))
        
        # Add some completely unique incidents for variety
        unique_incidents = [
            {
                "services": ["api-gateway"],
                "error_type": "SSLHandshakeException", 
                "error_messages": ["SSL certificate expired - handshake failed"],
                "root_causes": ["SSL certificate expired at midnight, not renewed"],
                "resolution_steps": ["1. Renew SSL certificate\n2. Deploy new cert\n3. Restart ingress"],
                "resolution_workflow": "manual_fix",
                "resolution_time_range": (25*60, 35*60),
                "resolution_confidence_range": (0.98, 0.99),
                "severity_weights": {"CRITICAL": 1.0},
                "auto_resolved_chance": 0.1,
                "tags": ["ssl", "certificate", "expired", "security"]
            },
            {
                "services": ["user-service"],
                "error_type": "NodeNotReadyException",
                "error_messages": ["Kubernetes node failure - pods evicted"],
                "root_causes": ["Worker node hardware failure caused pod evictions"],
                "resolution_steps": ["1. Drain failing node\n2. Scale replicas\n3. Replace node"],
                "resolution_workflow": "scale_service",
                "resolution_time_range": (40*60, 60*60), 
                "resolution_confidence_range": (0.85, 0.90),
                "severity_weights": {"HIGH": 1.0},
                "auto_resolved_chance": 0.3,
                "tags": ["kubernetes", "node_failure", "infrastructure", "scaling"]
            }
        ]
        
        # Add unique incidents if we have room
        remaining_slots = max(0, self.count - len(incidents_to_generate))
        for i in range(min(remaining_slots, len(unique_incidents))):
            template_name = f"unique_{i+1}"
            incidents_to_generate.append((template_name, unique_incidents[i]))
        
        # Shuffle to randomize order
        random.shuffle(incidents_to_generate)
        
        return incidents_to_generate[:self.count]
    
    def generate_incident(self, incident_id: str, template_name: str, template: Dict) -> Dict:
        """Generate a single incident document"""
        
        # Select random service
        service = random.choice(template["services"])
        
        # Select random error message and other template values
        error_message = random.choice(template["error_messages"])
        root_cause = random.choice(template["root_causes"])
        resolution_steps = random.choice(template["resolution_steps"])
        
        # Generate random timestamp in last 90 days
        random_offset = random.randint(0, int((self.end_time - self.start_time).total_seconds()))
        detected_at = self.start_time + timedelta(seconds=random_offset)
        
        # Calculate resolution time
        min_time, max_time = template["resolution_time_range"]
        resolution_time_seconds = random.randint(min_time, max_time)
        resolved_at = detected_at + timedelta(seconds=resolution_time_seconds)
        
        # Generate severity based on weights
        severity = np.random.choice(
            list(template["severity_weights"].keys()),
            p=list(template["severity_weights"].values())
        )
        
        # Generate confidence score
        min_conf, max_conf = template["resolution_confidence_range"]
        resolution_confidence = round(random.uniform(min_conf, max_conf), 3)
        
        # Generate error signature and embedding
        error_signature = self.generate_error_signature(service, template["error_type"])
        error_signature_embedding = self.generate_embedding(error_message)
        
        # Determine if auto-resolved
        auto_resolved = random.random() < template["auto_resolved_chance"]
        
        incident = {
            "incident_id": incident_id,
            "@timestamp": detected_at.isoformat() + "Z",
            "detected_at": detected_at.isoformat() + "Z", 
            "resolved_at": resolved_at.isoformat() + "Z",
            "status": "resolved",
            "severity": severity,
            "service": service,
            "error_type": template["error_type"],
            "error_message": error_message,
            "error_signature": error_signature,
            "root_cause": root_cause,
            "resolution_steps": resolution_steps,
            "resolution_workflow": template["resolution_workflow"],
            "resolution_time_seconds": resolution_time_seconds,
            "resolution_confidence": resolution_confidence,
            "auto_resolved": auto_resolved,
            "tags": template["tags"],
            "environment": "production"
        }
        
        # Add embedding only if available
        if error_signature_embedding is not None:
            incident["error_signature_embedding"] = error_signature_embedding
        
        return incident
    
    def generate_incidents(self, dry_run: bool = False) -> int:
        """Generate all incidents"""
        
        # Select incidents to generate
        incidents_to_generate = self.select_incidents_to_generate()
        
        print(f"📋 Generating {len(incidents_to_generate)} historical incidents...")
        
        batch = []
        batch_size = 50
        
        with tqdm(total=len(incidents_to_generate), desc="Generating incidents") as pbar:
            for i, incident_tuple in enumerate(incidents_to_generate):
                template_name, template = incident_tuple
                incident_id = f"INC-{i+1:03d}"
                
                incident = self.generate_incident(incident_id, template_name, template)
                
                if not dry_run:
                    timestamp = datetime.fromisoformat(incident["@timestamp"].replace("Z", ""))
                    batch.append({
                        "_op_type": "create",
                        "_index": "incidentiq-incidents",
                        "_source": incident
                    })
                
                # Show preview for first few incidents
                if i < 3:
                    print(f"\n📄 Preview - {incident_id}:")
                    print(f"   Service: {incident['service']}")
                    print(f"   Error: {incident['error_type']}")  
                    print(f"   Message: {incident['error_message'][:80]}...")
                    print(f"   Resolution: {incident['resolution_time_seconds']//60}min ({incident['resolution_confidence']:.2f} confidence)")
                
                # Bulk insert when batch is full
                if not dry_run and len(batch) >= batch_size:
                    try:
                        success, errors = helpers.bulk(self.es, batch, raise_on_error=False)
                        if errors:
                            print(f"\n⚠️  {len(errors)} incidents failed to index")
                    except Exception as e:
                        print(f"\n⚠️  Bulk insert error: {e}")
                    batch = []
                
                pbar.update(1)
        
        # Insert remaining documents
        if not dry_run and batch:
            try:
                success, errors = helpers.bulk(self.es, batch, raise_on_error=False)
                if errors:
                    print(f"\n⚠️  {len(errors)} incidents in final batch failed to index")
                    if errors:
                        print(f"First error: {errors[0]}")
            except Exception as e:
                print(f"\n⚠️  Final bulk insert error: {e}")
        
        return len(incidents_to_generate)

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
    parser = argparse.ArgumentParser(description="Generate historical incidents for IncidentIQ")
    parser.add_argument("--count", type=int, default=25, help="Number of incidents to generate")
    parser.add_argument("--dry-run", action="store_true", help="Preview without inserting data")
    
    args = parser.parse_args()
    
    print("📚 IncidentIQ Historical Incident Generator")
    print("=" * 50)
    
    # Setup Elasticsearch
    try:
        es = setup_elasticsearch()
        es.info()  # Test connection
        print("✅ Connected to Elasticsearch")
    except Exception as e:
        print(f"❌ Failed to connect to Elasticsearch: {e}")
        return 1
    
    print(f"📋 Configuration:")
    print(f"   • Incidents to generate: {args.count}")
    print(f"   • Time range: Last 90 days")
    print(f"   • Dry run: {'Yes' if args.dry_run else 'No'}")
    print()
    
    # Generate incidents
    generator = IncidentGenerator(es, count=args.count)
    
    start_time = datetime.utcnow()
    
    incident_count = generator.generate_incidents(dry_run=args.dry_run)
    
    elapsed = datetime.utcnow() - start_time
    
    print()
    print("📈 Summary:")
    print(f"   • Total incidents: {incident_count}")
    print(f"   • Execution time: {elapsed.total_seconds():.1f} seconds")
    print(f"   • Incident types: {len(INCIDENT_TEMPLATES)} templates + unique variants")
    
    if args.dry_run:
        print("   • This was a dry run - no data was inserted")
    else:
        print("   • Incidents successfully inserted into Elasticsearch")
    
    print()
    print("🎯 Next steps:")
    print("   1. Test similarity search with test queries")
    print("   2. Verify incident variety in Kibana")
    print("   3. Generate incident simulation for demo")
    
    return 0

if __name__ == "__main__":
    exit(main())