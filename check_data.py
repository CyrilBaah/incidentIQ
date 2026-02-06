#!/usr/bin/env python3
"""Quick data verification script"""
from elasticsearch import Elasticsearch
import os
from dotenv import load_dotenv

load_dotenv()
es = Elasticsearch(
    cloud_id=os.getenv('ELASTIC_CLOUD_ID'),
    api_key=os.getenv('ELASTIC_API_KEY')
)

print('📊 Current Data Status:')
print('=' * 50)

try:
    logs = es.count(index='logs-*')['count']
    print(f"  ✅ Logs: {logs:,}")
except:
    print(f"  ❌ Logs: 0")

try:
    metrics = es.count(index='metrics-*')['count']
    print(f"  ✅ Metrics: {metrics:,}")
except:
    print(f"  ❌ Metrics: 0")

try:
    incidents = es.count(index='incidentiq-incidents')['count']
    print(f"  ✅ Incidents: {incidents:,}")
except:
    print(f"  ❌ Incidents: 0")

try:
    runbooks = es.count(index='incidentiq-docs-runbooks')['count']
    print(f"  ✅ Runbooks: {runbooks:,}")
except:
    print(f"  ❌ Runbooks: 0")

try:
    baselines = es.count(index='baselines-*')['count']
    print(f"  ✅ Baselines: {baselines:,}")
except:
    print(f"  ❌ Baselines: 0")

try:
    config = es.count(index='config-*')['count']
    print(f"  ✅ Config: {config:,}")
except:
    print(f"  ❌ Config: 0")

print('=' * 50)
