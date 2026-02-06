# IncidentIQ ES|QL Queries

This directory contains ES|QL queries for the IncidentIQ Detective Agent system. These queries enable real-time anomaly detection, root cause analysis, trend monitoring, and baseline calculations.

## 📋 Query Files

### 1. detect_anomalies.esql
**Purpose**: Real-time anomaly detection using statistical baselines
- **Execution**: Every 2 minutes by Detective Agent
- **Performance**: <5 seconds on millions of logs
- **Output**: Top 10 services showing anomalous behavior

**Template Variables**:
- `$time_window`: Analysis window (default: "2m")
- `$anomaly_threshold`: Sigma threshold (default: 3.0)

**Key Features**:
- Z-score calculation for error rates, latency, and CPU
- Severity classification (CRITICAL >5σ, HIGH >3σ, MEDIUM >2σ)
- Enrichment with baseline statistics

### 2. correlate_root_causes.esql
**Purpose**: Root cause correlation analysis during incidents
- **Execution**: On-demand when incident detected
- **Performance**: <5 seconds for correlation analysis
- **Output**: Services ranked by root cause likelihood

**Template Variables**:
- `$incident_start`: Incident detection timestamp
- `$affected_service`: Primary affected service
- `$lookback_minutes`: Analysis window (default: 30)

**Key Features**:
- Multi-factor impact scoring
- Deployment event correlation
- Resource pressure analysis
- Service dependency weighting

### 3. analyze_trends.esql
**Purpose**: Trend analysis for predictive incident detection
- **Execution**: Hourly by Predictive Agent
- **Performance**: <5 seconds for 24 hours of data
- **Output**: Services showing concerning trends

**Template Variables**:
- `$analysis_hours`: Hours of history (default: 24)
- `$bucket_size`: Time bucket size (default: "1h")

**Key Features**:
- Rate of change calculations
- Trend classification (increasing/decreasing/stable)
- Risk prediction scoring
- Degradation pattern detection

### 4. calculate_baselines.esql
**Purpose**: Daily baseline calculation for anomaly detection
- **Execution**: Daily by Baseline Calculator Agent
- **Performance**: <10 seconds for 7 days of data
- **Output**: Statistical baselines per service

**Template Variables**:
- `$calculation_days`: History window (default: 7)
- `$exclude_incidents`: Exclude incident periods (default: true)

**Key Features**:
- Mean and standard deviation calculation
- P95 percentile computation
- Data quality assessment
- Incident period exclusion

## 🔧 Usage Examples

### Python Integration
```python
from elasticsearch import Elasticsearch

# Initialize client
es = Elasticsearch(cloud_id=..., api_key=...)

# Execute anomaly detection
query = open('detect_anomalies.esql', 'r').read()
query = query.replace('$time_window', '5m')
query = query.replace('$anomaly_threshold', '2.5')

result = es.esql.query(query=query)
anomalies = result['values']
```

### Direct ES|QL Console
```sql
-- Real-time anomaly detection
FROM incidentiq-logs-*, incidentiq-metrics-*
| WHERE @timestamp > NOW() - 2m
| STATS 
    total_logs = COUNT(),
    error_count = COUNT_IF(level == "ERROR")
  BY service
-- ... rest of query
```

## 📊 Performance Optimization

### Index Patterns
- `incidentiq-logs-*`: Application logs
- `incidentiq-metrics-*`: System metrics  
- `baselines-services`: Service baselines (for enrichment)
- `config-service-dependencies`: Service topology

### Query Optimization Tips
1. **Time Filtering**: Always filter by `@timestamp` first
2. **Field Selection**: Use `KEEP` to limit output fields
3. **Aggregation Ordering**: Aggregate early, filter late
4. **Enrichment Placement**: Enrich after aggregation
5. **Limit Results**: Always use `LIMIT` for top-N queries

## 🚨 Alert Thresholds

### Anomaly Detection
- **CRITICAL**: >5 standard deviations
- **HIGH**: >3 standard deviations  
- **MEDIUM**: >2 standard deviations
- **LOW**: >1 standard deviation

### Trend Analysis
- **High Risk**: Degradation score ≥4
- **Medium Risk**: Degradation score ≥2
- **Low Risk**: Degradation score ≥1
- **Stable**: Degradation score <1

## 🔄 Execution Schedule

| Query | Agent | Frequency | Purpose |
|-------|-------|-----------|---------|
| detect_anomalies | Detective | 2 minutes | Real-time detection |
| correlate_root_causes | Detective | On-demand | Incident analysis |
| analyze_trends | Predictive | 1 hour | Trend monitoring |
| calculate_baselines | Baseline | 1 day | Statistical updates |

## ⚠️ Prerequisites

1. **Enrich Policies**: Must be deployed and executed
   - `service_baselines` (for anomaly detection)
   - `service_dependencies` (for root cause analysis)

2. **Data Requirements**:
   - At least 7 days of historical data for baselines
   - Consistent service naming across logs and metrics
   - Proper timestamp formatting (`@timestamp`)

3. **Index Templates**: Must be deployed for data structure consistency

## 🧪 Testing

```bash
# Test query syntax
curl -X POST "https://your-cluster.es.io/_esql" \
  -H "Authorization: ApiKey your-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "FROM incidentiq-logs-* | LIMIT 1"}'

# Performance testing
time curl -X POST "https://your-cluster.es.io/_esql" \
  -H "Authorization: ApiKey your-key" \
  -d @detect_anomalies.esql
```

## 🔧 Maintenance

- **Weekly**: Review baseline calculation quality
- **Monthly**: Optimize query performance
- **Quarterly**: Update statistical thresholds
- **On Schema Changes**: Update field mappings in queries