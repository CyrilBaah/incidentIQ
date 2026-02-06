#!/usr/bin/env python3
"""
Generate service configuration data for IncidentIQ
Usage:
    python data/generate_service_config.py                    # Static baselines
    python data/generate_service_config.py --recalculate       # Calculate from ES
    python data/generate_service_config.py --recalculate --days 30
    python data/generate_service_config.py --dry-run           # Preview only
    python data/generate_service_config.py --verify-only       # Just verify
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Index names
DEPENDENCIES_INDEX = "config-service-dependencies"
BASELINES_INDEX = "baselines-services"
LOGS_INDEX_PATTERN = "logs-*"
METRICS_INDEX_PATTERN = "metrics-*"

# Service dependency configuration
SERVICE_DEPENDENCIES = {
    "api-gateway": {
        "upstream_services": [],  # Entry point
        "downstream_services": ["auth-service", "user-service", "payment-service"],
        "dependency_criticality": 1.0,
        "sla_target_p95": 200,
        "owner_team": "platform",
        "on_call_rotation": "platform-oncall",
        "description": "Main API gateway - entry point for all external traffic"
    },
    "auth-service": {
        "upstream_services": ["api-gateway"],
        "downstream_services": ["user-service"],
        "dependency_criticality": 0.9,
        "sla_target_p95": 100,
        "owner_team": "security",
        "on_call_rotation": "security-oncall",
        "description": "Authentication and authorization service"
    },
    "payment-service": {
        "upstream_services": ["api-gateway"],
        "downstream_services": ["notification-service"],
        "dependency_criticality": 0.95,
        "sla_target_p95": 500,
        "owner_team": "payments",
        "on_call_rotation": "payments-oncall",
        "description": "Payment processing and transaction management"
    },
    "notification-service": {
        "upstream_services": ["api-gateway", "payment-service"],
        "downstream_services": [],
        "dependency_criticality": 0.6,
        "sla_target_p95": 300,
        "owner_team": "communications",
        "on_call_rotation": "comms-oncall",
        "description": "Email, SMS, and push notification delivery"
    },
    "user-service": {
        "upstream_services": ["api-gateway", "auth-service"],
        "downstream_services": [],
        "dependency_criticality": 0.85,
        "sla_target_p95": 150,
        "owner_team": "core",
        "on_call_rotation": "core-oncall",
        "description": "User profile and account management"
    }
}

# Static baseline estimates (used when --recalculate is not specified)
STATIC_BASELINES = {
    "api-gateway": {
        "baseline_error_mean": 200.0,
        "baseline_error_stddev": 45.0,
        "baseline_error_p95": 290.0,
        "baseline_latency_mean": 150.0,
        "baseline_latency_stddev": 30.0,
        "baseline_latency_p95": 210.0,
        "baseline_cpu_mean": 45.0,
        "baseline_cpu_stddev": 8.0,
        "baseline_memory_mean": 65.0,
        "baseline_memory_stddev": 5.0
    },
    "auth-service": {
        "baseline_error_mean": 40.0,
        "baseline_error_stddev": 12.0,
        "baseline_error_p95": 64.0,
        "baseline_latency_mean": 80.0,
        "baseline_latency_stddev": 20.0,
        "baseline_latency_p95": 120.0,
        "baseline_cpu_mean": 35.0,
        "baseline_cpu_stddev": 7.0,
        "baseline_memory_mean": 55.0,
        "baseline_memory_stddev": 4.0
    },
    "payment-service": {
        "baseline_error_mean": 60.0,
        "baseline_error_stddev": 18.0,
        "baseline_error_p95": 96.0,
        "baseline_latency_mean": 250.0,
        "baseline_latency_stddev": 50.0,
        "baseline_latency_p95": 350.0,
        "baseline_cpu_mean": 50.0,
        "baseline_cpu_stddev": 10.0,
        "baseline_memory_mean": 70.0,
        "baseline_memory_stddev": 6.0
    },
    "notification-service": {
        "baseline_error_mean": 100.0,
        "baseline_error_stddev": 25.0,
        "baseline_error_p95": 150.0,
        "baseline_latency_mean": 200.0,
        "baseline_latency_stddev": 60.0,
        "baseline_latency_p95": 320.0,
        "baseline_cpu_mean": 30.0,
        "baseline_cpu_stddev": 6.0,
        "baseline_memory_mean": 50.0,
        "baseline_memory_stddev": 5.0
    },
    "user-service": {
        "baseline_error_mean": 50.0,
        "baseline_error_stddev": 15.0,
        "baseline_error_p95": 80.0,
        "baseline_latency_mean": 120.0,
        "baseline_latency_stddev": 25.0,
        "baseline_latency_p95": 170.0,
        "baseline_cpu_mean": 40.0,
        "baseline_cpu_stddev": 8.0,
        "baseline_memory_mean": 60.0,
        "baseline_memory_stddev": 5.0
    }
}


class ServiceConfigGenerator:
    """Generate service dependencies and baseline statistics"""
    
    def __init__(self, es: Elasticsearch, dry_run: bool = False):
        """
        Initialize generator
        
        Args:
            es: Elasticsearch client
            dry_run: If True, don't write to Elasticsearch
        """
        self.es = es
        self.dry_run = dry_run
        
    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """
        Validate service dependency graph
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        # Check for circular dependencies using DFS
        def has_cycle(service: str, visited: set, rec_stack: set) -> bool:
            visited.add(service)
            rec_stack.add(service)
            
            for downstream in SERVICE_DEPENDENCIES[service]["downstream_services"]:
                if downstream not in visited:
                    if has_cycle(downstream, visited, rec_stack):
                        return True
                elif downstream in rec_stack:
                    errors.append(f"Circular dependency detected: {service} -> {downstream}")
                    return True
                    
            rec_stack.remove(service)
            return False
        
        visited = set()
        for service in SERVICE_DEPENDENCIES.keys():
            if service not in visited:
                if has_cycle(service, visited, set()):
                    return False, errors
        
        # Validate upstream/downstream consistency
        for service, config in SERVICE_DEPENDENCIES.items():
            for downstream in config["downstream_services"]:
                if downstream not in SERVICE_DEPENDENCIES:
                    errors.append(f"Service {service} references unknown downstream: {downstream}")
                elif service not in SERVICE_DEPENDENCIES[downstream]["upstream_services"]:
                    errors.append(f"Inconsistent dependency: {service} lists {downstream} as downstream, "
                                f"but {downstream} doesn't list {service} as upstream")
        
        return len(errors) == 0, errors
    
    def generate_dependencies(self) -> List[Dict]:
        """
        Generate service dependency documents
        
        Returns:
            List of dependency documents
        """
        print("\n📋 Generating service dependencies...")
        
        documents = []
        for service, config in SERVICE_DEPENDENCIES.items():
            doc = {
                "service": service,
                "upstream_services": config["upstream_services"],
                "downstream_services": config["downstream_services"],
                "dependency_criticality": config["dependency_criticality"],
                "sla_target_p95": config["sla_target_p95"],
                "owner_team": config["owner_team"],
                "on_call_rotation": config["on_call_rotation"],
                "description": config["description"],
                "generated_at": datetime.utcnow().isoformat() + "Z"
            }
            documents.append(doc)
            
        print(f"   ✓ Generated {len(documents)} service dependency documents")
        return documents
    
    def calculate_baselines_from_elasticsearch(self, days: int = 7) -> List[Dict]:
        """
        Calculate baseline statistics from Elasticsearch data
        
        Args:
            days: Number of days of data to analyze
            
        Returns:
            List of baseline documents
        """
        print(f"\n📊 Calculating baselines from last {days} days of data...")
        
        # Calculate time range
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)
        
        baselines = []
        
        for service in tqdm(SERVICE_DEPENDENCIES.keys(), desc="Processing services"):
            try:
                # Query metrics data for this service
                query = {
                    "bool": {
                        "must": [
                            {"term": {"service": service}},
                            {
                                "range": {
                                    "@timestamp": {
                                        "gte": start_time.isoformat() + "Z",
                                        "lte": end_time.isoformat() + "Z"
                                    }
                                }
                            }
                        ]
                    }
                }
                
                # Fetch metrics data
                metrics_response = self.es.search(
                    index=METRICS_INDEX_PATTERN,
                    query=query,
                    size=10000,  # Adjust based on data volume
                    _source=["cpu_percent", "memory_percent", "error_rate", "avg_response_time"]
                )
                
                # Fetch logs for error counting
                logs_response = self.es.search(
                    index=LOGS_INDEX_PATTERN,
                    query=query,
                    size=0,
                    aggs={
                        "errors_over_time": {
                            "date_histogram": {
                                "field": "@timestamp",
                                "fixed_interval": "1h"
                            },
                            "aggs": {
                                "error_count": {
                                    "filter": {"term": {"level": "ERROR"}}
                                }
                            }
                        }
                    }
                )
                
                # Extract metrics
                metrics_hits = metrics_response["hits"]["hits"]
                
                if len(metrics_hits) < 100:
                    print(f"\n   ⚠️  Warning: Only {len(metrics_hits)} samples for {service} - using static baseline")
                    baseline = self._get_static_baseline(service, days)
                else:
                    # Calculate statistics
                    cpu_values = [hit["_source"].get("cpu_percent", 0) for hit in metrics_hits if "cpu_percent" in hit["_source"]]
                    memory_values = [hit["_source"].get("memory_percent", 0) for hit in metrics_hits if "memory_percent" in hit["_source"]]
                    error_rates = [hit["_source"].get("error_rate", 0) for hit in metrics_hits if "error_rate" in hit["_source"]]
                    latencies = [hit["_source"].get("avg_response_time", 0) for hit in metrics_hits if "avg_response_time" in hit["_source"]]
                    
                    # Extract error counts from aggregation
                    error_counts = []
                    if "aggregations" in logs_response:
                        for bucket in logs_response["aggregations"]["errors_over_time"]["buckets"]:
                            error_counts.append(bucket["error_count"]["doc_count"])
                    
                    baseline = {
                        "service": service,
                        # Error metrics
                        "baseline_error_mean": float(np.mean(error_counts)) if error_counts else 0.0,
                        "baseline_error_stddev": float(np.std(error_counts)) if error_counts else 0.0,
                        "baseline_error_p95": float(np.percentile(error_counts, 95)) if error_counts else 0.0,
                        # Latency metrics
                        "baseline_latency_mean": float(np.mean(latencies)) if latencies else 0.0,
                        "baseline_latency_stddev": float(np.std(latencies)) if latencies else 0.0,
                        "baseline_latency_p95": float(np.percentile(latencies, 95)) if latencies else 0.0,
                        # CPU metrics
                        "baseline_cpu_mean": float(np.mean(cpu_values)) if cpu_values else 0.0,
                        "baseline_cpu_stddev": float(np.std(cpu_values)) if cpu_values else 0.0,
                        # Memory metrics
                        "baseline_memory_mean": float(np.mean(memory_values)) if memory_values else 0.0,
                        "baseline_memory_stddev": float(np.std(memory_values)) if memory_values else 0.0,
                        # Metadata
                        "calculation_period_days": days,
                        "sample_count": len(metrics_hits),
                        "last_calculated": datetime.utcnow().isoformat() + "Z",
                        "calculated_from": "elasticsearch"
                    }
                
                baselines.append(baseline)
                
            except Exception as e:
                print(f"\n   ⚠️  Error calculating baseline for {service}: {e}")
                print(f"   → Using static baseline instead")
                baseline = self._get_static_baseline(service, days)
                baselines.append(baseline)
        
        print(f"\n   ✓ Calculated baselines for {len(baselines)} services")
        return baselines
    
    def _get_static_baseline(self, service: str, days: int = 7) -> Dict:
        """
        Get static baseline for a service
        
        Args:
            service: Service name
            days: Period (for metadata only)
            
        Returns:
            Baseline document with static values
        """
        static = STATIC_BASELINES.get(service, {})
        
        return {
            "service": service,
            "baseline_error_mean": static.get("baseline_error_mean", 0.0),
            "baseline_error_stddev": static.get("baseline_error_stddev", 0.0),
            "baseline_error_p95": static.get("baseline_error_p95", 0.0),
            "baseline_latency_mean": static.get("baseline_latency_mean", 0.0),
            "baseline_latency_stddev": static.get("baseline_latency_stddev", 0.0),
            "baseline_latency_p95": static.get("baseline_latency_p95", 0.0),
            "baseline_cpu_mean": static.get("baseline_cpu_mean", 0.0),
            "baseline_cpu_stddev": static.get("baseline_cpu_stddev", 0.0),
            "baseline_memory_mean": static.get("baseline_memory_mean", 0.0),
            "baseline_memory_stddev": static.get("baseline_memory_stddev", 0.0),
            "calculation_period_days": days,
            "sample_count": 0,
            "last_calculated": datetime.utcnow().isoformat() + "Z",
            "calculated_from": "static"
        }
    
    def generate_static_baselines(self) -> List[Dict]:
        """
        Generate baselines from static configuration
        
        Returns:
            List of baseline documents
        """
        print("\n📊 Generating static baselines...")
        
        baselines = []
        for service in SERVICE_DEPENDENCIES.keys():
            baseline = self._get_static_baseline(service, days=7)
            baselines.append(baseline)
        
        print(f"   ✓ Generated {len(baselines)} static baseline documents")
        return baselines
    
    def write_dependencies(self, documents: List[Dict]) -> int:
        """
        Write dependency documents to Elasticsearch
        
        Args:
            documents: List of dependency documents
            
        Returns:
            Number of documents written
        """
        if self.dry_run:
            print(f"\n[DRY RUN] Would write {len(documents)} documents to {DEPENDENCIES_INDEX}")
            return 0
        
        print(f"\n💾 Writing dependencies to {DEPENDENCIES_INDEX}...")
        
        # Delete existing index
        if self.es.indices.exists(index=DEPENDENCIES_INDEX):
            self.es.indices.delete(index=DEPENDENCIES_INDEX)
            print(f"   → Deleted existing index")
        
        # Bulk index
        actions = [
            {
                "_index": DEPENDENCIES_INDEX,
                "_id": doc["service"],
                "_source": doc
            }
            for doc in documents
        ]
        
        success, failed = helpers.bulk(self.es, actions, raise_on_error=False)
        print(f"   ✓ Wrote {success} dependency documents")
        
        if failed:
            print(f"   ⚠️  {len(failed)} documents failed")
        
        return success
    
    def write_baselines(self, documents: List[Dict]) -> int:
        """
        Write baseline documents to Elasticsearch
        
        Args:
            documents: List of baseline documents
            
        Returns:
            Number of documents written
        """
        if self.dry_run:
            print(f"\n[DRY RUN] Would write {len(documents)} documents to {BASELINES_INDEX}")
            return 0
        
        print(f"\n💾 Writing baselines to {BASELINES_INDEX}...")
        
        # Delete existing index
        if self.es.indices.exists(index=BASELINES_INDEX):
            self.es.indices.delete(index=BASELINES_INDEX)
            print(f"   → Deleted existing index")
        
        # Bulk index
        actions = [
            {
                "_index": BASELINES_INDEX,
                "_id": doc["service"],
                "_source": doc
            }
            for doc in documents
        ]
        
        success, failed = helpers.bulk(self.es, actions, raise_on_error=False)
        print(f"   ✓ Wrote {success} baseline documents")
        
        if failed:
            print(f"   ⚠️  {len(failed)} documents failed")
        
        return success
    
    def execute_enrich_policies(self):
        """Execute enrich policies to prepare for ES|QL queries"""
        if self.dry_run:
            print("\n[DRY RUN] Would execute enrich policies")
            return
        
        print("\n🔄 Executing enrich policies...")
        
        policies = ["service_dependencies", "service_baselines"]
        
        for policy_name in policies:
            try:
                # Check if policy exists
                try:
                    self.es.enrich.get_policy(name=policy_name)
                except:
                    print(f"   ⚠️  Policy '{policy_name}' not found - skipping")
                    print(f"      Create it from elasticsearch-config/enrich-policies/{policy_name}.json")
                    continue
                
                # Execute policy
                self.es.enrich.execute_policy(name=policy_name, wait_for_completion=True)
                print(f"   ✓ Executed policy: {policy_name}")
                
            except Exception as e:
                print(f"   ⚠️  Failed to execute policy '{policy_name}': {e}")
    
    def verify_data(self) -> Tuple[bool, List[str]]:
        """
        Verify that data was written correctly
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        print("\n🔍 Verifying data integrity...")
        
        errors = []
        
        # Check dependencies index
        try:
            if not self.es.indices.exists(index=DEPENDENCIES_INDEX):
                errors.append(f"Index {DEPENDENCIES_INDEX} does not exist")
            else:
                count = self.es.count(index=DEPENDENCIES_INDEX)["count"]
                expected = len(SERVICE_DEPENDENCIES)
                
                if count != expected:
                    errors.append(f"Expected {expected} dependency docs, found {count}")
                else:
                    print(f"   ✓ Dependencies: {count}/{expected} documents")
        except Exception as e:
            errors.append(f"Error checking dependencies: {e}")
        
        # Check baselines index
        try:
            if not self.es.indices.exists(index=BASELINES_INDEX):
                errors.append(f"Index {BASELINES_INDEX} does not exist")
            else:
                count = self.es.count(index=BASELINES_INDEX)["count"]
                expected = len(SERVICE_DEPENDENCIES)
                
                if count != expected:
                    errors.append(f"Expected {expected} baseline docs, found {count}")
                else:
                    print(f"   ✓ Baselines: {count}/{expected} documents")
                    
                # Verify baseline values are reasonable
                for service in SERVICE_DEPENDENCIES.keys():
                    try:
                        doc = self.es.get(index=BASELINES_INDEX, id=service)
                        source = doc["_source"]
                        
                        # Check for NaN or negative values
                        for field in ["baseline_error_mean", "baseline_latency_mean", 
                                     "baseline_cpu_mean", "baseline_memory_mean"]:
                            value = source.get(field, 0)
                            if value < 0 or np.isnan(value):
                                errors.append(f"Invalid {field} for {service}: {value}")
                    except Exception as e:
                        errors.append(f"Error verifying baseline for {service}: {e}")
                        
        except Exception as e:
            errors.append(f"Error checking baselines: {e}")
        
        if errors:
            print(f"\n   ❌ Verification failed with {len(errors)} errors:")
            for error in errors:
                print(f"      • {error}")
            return False, errors
        else:
            print(f"\n   ✅ All verifications passed")
            return True, []


def init_elasticsearch() -> Optional[Elasticsearch]:
    """Initialize Elasticsearch connection"""
    try:
        cloud_id = os.getenv("ELASTIC_CLOUD_ID")
        api_key = os.getenv("ELASTIC_API_KEY")
        
        if not cloud_id or not api_key:
            print("❌ ELASTIC_CLOUD_ID or ELASTIC_API_KEY not set in .env")
            return None
        
        es = Elasticsearch(
            cloud_id=cloud_id,
            api_key=api_key
        )
        
        # Test connection
        info = es.info()
        print(f"✅ Connected to Elasticsearch: {info['cluster_name']}")
        
        return es
        
    except Exception as e:
        print(f"❌ Elasticsearch connection failed: {e}")
        return None


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Generate service configuration data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate with static baselines (fast)
  python data/generate_service_config.py
  
  # Recalculate baselines from actual Elasticsearch data
  python data/generate_service_config.py --recalculate
  
  # Use 30-day baseline period
  python data/generate_service_config.py --recalculate --days 30
  
  # Preview without writing
  python data/generate_service_config.py --dry-run
  
  # Just verify existing data
  python data/generate_service_config.py --verify-only
        """
    )
    
    parser.add_argument(
        "--recalculate",
        action="store_true",
        help="Calculate baselines from Elasticsearch data (requires existing metrics)"
    )
    
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days for baseline calculation (default: 7)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only, don't write to Elasticsearch"
    )
    
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing data, don't regenerate"
    )
    
    args = parser.parse_args()
    
    # Connect to Elasticsearch
    es = init_elasticsearch()
    if not es:
        return 1
    
    # Initialize generator
    generator = ServiceConfigGenerator(es, dry_run=args.dry_run)
    
    # Verify only mode
    if args.verify_only:
        is_valid, errors = generator.verify_data()
        return 0 if is_valid else 1
    
    # Validate dependency graph
    print("\n🔍 Validating service dependency graph...")
    is_valid, errors = generator.validate_dependencies()
    
    if not is_valid:
        print(f"\n❌ Dependency validation failed:")
        for error in errors:
            print(f"   • {error}")
        return 1
    
    print("   ✓ Dependency graph is valid (no cycles)")
    
    # Generate dependencies
    dependencies = generator.generate_dependencies()
    
    # Generate or calculate baselines
    if args.recalculate:
        print(f"\n📊 Recalculating baselines from Elasticsearch data...")
        print(f"   Note: This requires existing metrics data from generate_baselines.py")
        baselines = generator.calculate_baselines_from_elasticsearch(days=args.days)
    else:
        baselines = generator.generate_static_baselines()
    
    # Write to Elasticsearch
    dep_count = generator.write_dependencies(dependencies)
    baseline_count = generator.write_baselines(baselines)
    
    # Execute enrich policies
    generator.execute_enrich_policies()
    
    # Verify
    is_valid, errors = generator.verify_data()
    
    # Summary
    print("\n" + "="*70)
    print("📊 SUMMARY")
    print("="*70)
    print(f"Dependencies written:  {dep_count}/{len(dependencies)}")
    print(f"Baselines written:     {baseline_count}/{len(baselines)}")
    print(f"Verification:          {'✅ PASSED' if is_valid else '❌ FAILED'}")
    print(f"Mode:                  {'🔄 Recalculated from ES' if args.recalculate else '📋 Static configuration'}")
    
    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No data was actually written")
    
    print("\n✅ Service configuration complete!")
    print("\nNext steps:")
    print("  1. Run generate_baselines.py to generate historical metrics")
    print("  2. Run generate_incidents.py to generate incident history")
    print("  3. Test with: python test_esql_queries.py")
    
    return 0 if is_valid else 1


if __name__ == "__main__":
    exit(main())
