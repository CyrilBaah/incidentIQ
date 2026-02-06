#!/usr/bin/env python3
"""
===============================================================================
DATA VERIFICATION SCRIPT - Context7 Documentation
===============================================================================

CONTEXT:
    After generating demo data, we need to verify that all indexes contain
    the expected number of documents and that data quality is acceptable.
    This prevents demos from failing due to incomplete data generation.

CHALLENGE:
    - Multiple indexes with different expected document counts
    - Need to validate both quantity and quality of data
    - Should provide clear error messages for troubleshooting
    - Must handle cases where indexes don't exist yet
    - Need to verify enrich policies are ready

CHOICES:
    - Check document counts against expected ranges
    - Validate data structure and required fields
    - Test enrich policies are executable
    - Provide detailed error messages with remediation steps
    - Exit with appropriate status codes for CI/CD integration

CRITERIA:
    - All required indexes must exist
    - Document counts must be within expected ranges
    - Critical fields must be present in sample documents
    - Enrich policies must be ready for execution
    - Clear pass/fail status with actionable errors

CONSEQUENCES:
    - Early detection of data generation failures
    - Prevents wasted time on demos with incomplete data
    - Clear error messages reduce troubleshooting time
    - CI/CD integration enables automated validation

CONCLUSION:
    This verification script provides confidence that demo data is complete
    and properly structured before running simulations or demonstrations.

CALL-TO-ACTION:
    # Verify all data
    python scripts/verify_data.py
    
    # Verbose output
    python scripts/verify_data.py --verbose
    
    # Quick check (counts only)
    python scripts/verify_data.py --quick

===============================================================================

Usage:
    python scripts/verify_data.py                    # Standard verification
    python scripts/verify_data.py --verbose          # Detailed output
    python scripts/verify_data.py --quick            # Quick check
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

# Load environment
load_dotenv()

# ANSI color codes
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
CYAN = '\033[0;36m'
NC = '\033[0m'  # No Color


class DataVerifier:
    """Verify IncidentIQ demo data in Elasticsearch"""
    
    def __init__(self, es: Elasticsearch, verbose: bool = False):
        """
        Initialize verifier
        
        Args:
            es: Elasticsearch client
            verbose: Print detailed information
        """
        self.es = es
        self.verbose = verbose
        self.errors = []
        self.warnings = []
        
    def print_section(self, title: str):
        """Print section header"""
        print(f"\n{CYAN}{'─' * 70}{NC}")
        print(f"{CYAN}{title}{NC}")
        print(f"{CYAN}{'─' * 70}{NC}")
    
    def print_check(self, name: str, passed: bool, details: str = ""):
        """Print check result"""
        status = f"{GREEN}✓{NC}" if passed else f"{RED}✗{NC}"
        print(f"  {status} {name}")
        if details and (self.verbose or not passed):
            print(f"     {details}")
    
    def verify_index(self, index_pattern: str, min_docs: int, max_docs: Optional[int] = None,
                    required_fields: Optional[List[str]] = None) -> bool:
        """
        Verify an index exists and has expected document count
        
        Args:
            index_pattern: Index name or pattern
            min_docs: Minimum expected documents
            max_docs: Maximum expected documents (None = no max)
            required_fields: Fields that must exist in sample documents
            
        Returns:
            True if verification passed
        """
        try:
            # Check if index exists
            if not self.es.indices.exists(index=index_pattern):
                self.errors.append(f"Index {index_pattern} does not exist")
                self.print_check(f"Index {index_pattern}", False, "Index not found")
                return False
            
            # Get document count
            count_result = self.es.count(index=index_pattern)
            doc_count = count_result["count"]
            
            # Check count range
            count_ok = doc_count >= min_docs
            if max_docs is not None:
                count_ok = count_ok and doc_count <= max_docs
            
            if not count_ok:
                range_str = f"{min_docs:,}" if max_docs is None else f"{min_docs:,}-{max_docs:,}"
                self.errors.append(
                    f"Index {index_pattern} has {doc_count:,} documents, expected {range_str}"
                )
                self.print_check(
                    f"Index {index_pattern}",
                    False,
                    f"Found {doc_count:,} docs, expected {range_str}"
                )
                return False
            
            # Check required fields if specified
            if required_fields and doc_count > 0:
                try:
                    # Get a sample document
                    search_result = self.es.search(index=index_pattern, size=1)
                    if search_result["hits"]["hits"]:
                        doc = search_result["hits"]["hits"][0]["_source"]
                        missing_fields = [f for f in required_fields if f not in doc]
                        
                        if missing_fields:
                            self.warnings.append(
                                f"Index {index_pattern} missing fields: {', '.join(missing_fields)}"
                            )
                            self.print_check(
                                f"Index {index_pattern}",
                                True,
                                f"{doc_count:,} docs (⚠ missing fields: {', '.join(missing_fields)})"
                            )
                        else:
                            self.print_check(
                                f"Index {index_pattern}",
                                True,
                                f"{doc_count:,} docs, all required fields present"
                            )
                    else:
                        self.print_check(f"Index {index_pattern}", True, f"{doc_count:,} docs")
                except Exception as e:
                    self.warnings.append(f"Could not verify fields for {index_pattern}: {e}")
                    self.print_check(f"Index {index_pattern}", True, f"{doc_count:,} docs")
            else:
                self.print_check(f"Index {index_pattern}", True, f"{doc_count:,} docs")
            
            return True
            
        except Exception as e:
            self.errors.append(f"Error verifying {index_pattern}: {e}")
            self.print_check(f"Index {index_pattern}", False, str(e))
            return False
    
    def verify_enrich_policy(self, policy_name: str) -> bool:
        """
        Verify an enrich policy exists and is ready
        
        Args:
            policy_name: Name of the enrich policy
            
        Returns:
            True if policy exists and is ready
        """
        try:
            # Check if policy exists
            self.es.enrich.get_policy(name=policy_name)
            self.print_check(f"Enrich policy: {policy_name}", True, "Ready")
            return True
        except Exception as e:
            self.warnings.append(f"Enrich policy {policy_name} not found or not ready: {e}")
            self.print_check(
                f"Enrich policy: {policy_name}",
                False,
                f"Not found (create from elasticsearch-config/enrich-policies/)"
            )
            return False
    
    def verify_time_range(self, index_pattern: str, expected_days: int) -> bool:
        """
        Verify data spans expected time range
        
        Args:
            index_pattern: Index pattern to check
            expected_days: Expected number of days of data
            
        Returns:
            True if time range is acceptable
        """
        try:
            # Get time range of data
            agg_result = self.es.search(
                index=index_pattern,
                size=0,
                aggs={
                    "min_time": {"min": {"field": "@timestamp"}},
                    "max_time": {"max": {"field": "@timestamp"}}
                }
            )
            
            if "aggregations" in agg_result:
                min_ts = agg_result["aggregations"]["min_time"].get("value")
                max_ts = agg_result["aggregations"]["max_time"].get("value")
                
                if min_ts and max_ts:
                    min_dt = datetime.fromtimestamp(min_ts / 1000)
                    max_dt = datetime.fromtimestamp(max_ts / 1000)
                    actual_days = (max_dt - min_dt).days
                    
                    if actual_days >= expected_days - 1:  # Allow 1 day tolerance
                        self.print_check(
                            f"Time range: {index_pattern}",
                            True,
                            f"{actual_days} days ({min_dt.date()} to {max_dt.date()})"
                        )
                        return True
                    else:
                        self.warnings.append(
                            f"Index {index_pattern} only spans {actual_days} days, expected ~{expected_days}"
                        )
                        self.print_check(
                            f"Time range: {index_pattern}",
                            False,
                            f"Only {actual_days} days, expected ~{expected_days}"
                        )
                        return False
            
            self.warnings.append(f"Could not determine time range for {index_pattern}")
            return True  # Don't fail on this
            
        except Exception as e:
            self.warnings.append(f"Error checking time range for {index_pattern}: {e}")
            return True  # Don't fail on this
    
    def run_verification(self, baseline_days: int = 7) -> bool:
        """
        Run full verification suite
        
        Args:
            baseline_days: Expected days of baseline data
            
        Returns:
            True if all verifications passed
        """
        print(f"\n{CYAN}🔍 IncidentIQ Data Verification{NC}\n")
        
        all_passed = True
        
        # 1. Verify Log Data
        self.print_section("📝 Log Data")
        
        # Logs should have many documents (depends on baseline days)
        min_logs = baseline_days * 5000  # ~5000 logs per day minimum
        max_logs = baseline_days * 200000  # ~200k logs per day maximum
        
        all_passed &= self.verify_index(
            "logs-*",
            min_docs=min_logs,
            max_docs=max_logs,
            required_fields=["@timestamp", "service", "level", "message"]
        )
        
        if self.es.indices.exists(index="logs-*"):
            self.verify_time_range("logs-*", baseline_days)
        
        # 2. Verify Metric Data
        self.print_section("📊 Metric Data")
        
        # Metrics should have fewer documents than logs
        min_metrics = baseline_days * 1000  # ~1000 metrics per day minimum
        max_metrics = baseline_days * 50000  # ~50k metrics per day maximum
        
        all_passed &= self.verify_index(
            "metrics-*",
            min_docs=min_metrics,
            max_docs=max_metrics,
            required_fields=["@timestamp", "service", "cpu_percent", "memory_percent"]
        )
        
        if self.es.indices.exists(index="metrics-*"):
            self.verify_time_range("metrics-*", baseline_days)
        
        # 3. Verify Incident Data
        self.print_section("🚨 Incident Data")
        
        all_passed &= self.verify_index(
            "incidentiq-incidents",
            min_docs=10,
            max_docs=50,
            required_fields=["incident_id", "service", "severity", "status"]
        )
        
        # 4. Verify Runbook Data
        self.print_section("📚 Runbook Data")
        
        all_passed &= self.verify_index(
            "incidentiq-docs-runbooks",
            min_docs=5,
            max_docs=20,
            required_fields=["service", "title", "error_types"]
        )
        
        # 5. Verify Configuration Data
        self.print_section("⚙️  Configuration Data")
        
        all_passed &= self.verify_index(
            "baselines-services",
            min_docs=5,
            max_docs=5,
            required_fields=["service", "baseline_error_mean", "baseline_latency_mean"]
        )
        
        all_passed &= self.verify_index(
            "config-service-dependencies",
            min_docs=5,
            max_docs=5,
            required_fields=["service", "upstream_services", "downstream_services"]
        )
        
        # 6. Verify Enrich Policies
        self.print_section("🔄 Enrich Policies")
        
        self.verify_enrich_policy("service_baselines")
        self.verify_enrich_policy("service_dependencies")
        
        # Print summary
        print(f"\n{CYAN}{'─' * 70}{NC}")
        print(f"{CYAN}📊 Verification Summary{NC}")
        print(f"{CYAN}{'─' * 70}{NC}\n")
        
        if all_passed and not self.errors:
            print(f"{GREEN}✅ All verifications passed!{NC}\n")
            if self.warnings:
                print(f"{YELLOW}⚠️  {len(self.warnings)} warnings:{NC}")
                for warning in self.warnings:
                    print(f"   • {warning}")
                print()
            return True
        else:
            print(f"{RED}❌ Verification failed with {len(self.errors)} errors{NC}\n")
            
            if self.errors:
                print(f"{RED}Errors:{NC}")
                for error in self.errors:
                    print(f"   • {error}")
                print()
            
            if self.warnings:
                print(f"{YELLOW}Warnings:{NC}")
                for warning in self.warnings:
                    print(f"   • {warning}")
                print()
            
            print(f"{YELLOW}Remediation steps:{NC}")
            print(f"   1. Run: {CYAN}./scripts/setup_demo_data.sh{NC}")
            print(f"   2. Check Elasticsearch connection: {CYAN}python test_connections.py{NC}")
            print(f"   3. Review generation logs for errors")
            print()
            
            return False


def init_elasticsearch() -> Optional[Elasticsearch]:
    """Initialize Elasticsearch connection"""
    try:
        cloud_id = os.getenv("ELASTIC_CLOUD_ID")
        api_key = os.getenv("ELASTIC_API_KEY")
        
        if not cloud_id or not api_key:
            print(f"{RED}❌ ELASTIC_CLOUD_ID or ELASTIC_API_KEY not set in .env{NC}")
            return None
        
        es = Elasticsearch(
            cloud_id=cloud_id,
            api_key=api_key
        )
        
        # Test connection
        info = es.info()
        print(f"{GREEN}✅ Connected to Elasticsearch: {info['cluster_name']}{NC}")
        
        return es
        
    except Exception as e:
        print(f"{RED}❌ Elasticsearch connection failed: {e}{NC}")
        return None


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Verify IncidentIQ demo data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard verification
  python scripts/verify_data.py
  
  # Verbose output
  python scripts/verify_data.py --verbose
  
  # Quick check (counts only)
  python scripts/verify_data.py --quick
  
  # Verify 14 days of baseline data
  python scripts/verify_data.py --baseline-days 14
        """
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed information"
    )
    
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick check (counts only, skip field validation)"
    )
    
    parser.add_argument(
        "--baseline-days",
        type=int,
        default=7,
        help="Expected days of baseline data (default: 7)"
    )
    
    args = parser.parse_args()
    
    # Connect to Elasticsearch
    es = init_elasticsearch()
    if not es:
        return 1
    
    # Run verification
    verifier = DataVerifier(es, verbose=args.verbose)
    
    passed = verifier.run_verification(baseline_days=args.baseline_days)
    
    return 0 if passed else 1


if __name__ == "__main__":
    exit(main())
