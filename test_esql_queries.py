#!/usr/bin/env python3
"""Test ES|QL queries"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

def load_query(filename):
    """Load ES|QL query from file"""
    with open(f"tools/esql/{filename}", 'r') as f:
        return f.read()

def test_query(es, query_name, template_vars=None):
    """Test an ES|QL query"""
    print(f"\n🧪 Testing {query_name}...")
    
    try:
        # Load query
        query = load_query(query_name)
        
        # Replace template variables
        if template_vars:
            for key, value in template_vars.items():
                query = query.replace(f"${key}", str(value))
        
        # Execute query
        result = es.esql.query(query=query)
        
        print(f"✅ Query executed successfully!")
        print(f"   Rows returned: {len(result.get('values', []))}")
        
        return True
        
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return False

def main():
    # Connect to Elasticsearch
    es = Elasticsearch(
        cloud_id=os.getenv("ELASTIC_CLOUD_ID"),
        api_key=os.getenv("ELASTIC_API_KEY")
    )
    
    print("="*60)
    print("ES|QL Query Tests")
    print("="*60)
    
    # Test 1: Detect anomalies
    test_query(es, "detect_anomalies.esql", {
        "time_window": "2m",
        "anomaly_threshold": "3.0"
    })
    
    # Test 2: Correlate root causes
    test_query(es, "correlate_root_causes.esql", {
        "incident_start": (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "affected_service": "api-gateway", 
        "lookback_minutes": "30"
    })
    
    # Test 3: Analyze trends
    test_query(es, "analyze_trends.esql", {
        "lookback_hours": "24",
        "bucket_interval": "1h"
    })
    
    # Test 4: Calculate baselines
    test_query(es, "calculate_baselines.esql", {
        "lookback_days": "7"
    })
    
    print("\n" + "="*60)
    print("✅ All query tests complete!")
    print("="*60)

if __name__ == "__main__":
    main()