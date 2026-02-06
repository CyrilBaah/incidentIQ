# IncidentIQ Elasticsearch Queries

Common queries for validating and exploring IncidentIQ demo data.

## Data Validation Queries

### Check Logs Count
```json
GET logs-*/_count
```
Expected: ~1.3M documents per day (7 days historical = ~9M total if all generated)

### Check Metrics Count
```json
GET metrics-*/_count
```
Expected: ~280K documents per day (7 days historical = ~2M total)

### Check Incidents Count
```json
GET incidentiq-incidents/_count
```
Expected: 25 incidents

### Check Runbooks Count
```json
GET incidentiq-docs-runbooks/_count
```
Expected: 10 runbooks (or 2 if only templates generated)

### Check Baselines Count
```json
GET baselines-*/_count
```
Expected: 5 services

### Check Service Dependencies Count
```json
GET config-*/_count
```
Expected: 5 services

## Data Exploration Queries

### Recent Incidents
```json
GET incidentiq-incidents/_search
{
  "size": 5,
  "sort": [{"@timestamp": "desc"}],
  "_source": ["incident_id", "service", "error_type", "severity", "status", "resolution_time_seconds"]
}
```

### Recent Logs
```json
GET logs-*/_search
{
  "size": 5,
  "sort": [{"@timestamp": "desc"}],
  "_source": ["@timestamp", "service", "level", "message", "error_type"]
}
```

### Recent Metrics
```json
GET metrics-*/_search
{
  "size": 5,
  "sort": [{"@timestamp": "desc"}],
  "_source": ["@timestamp", "service", "metric_type", "value"]
}
```

### All Runbooks
```json
GET incidentiq-docs-runbooks/_search
{
  "size": 20,
  "_source": ["runbook_id", "service", "title", "error_types", "success_rate", "tags"]
}
```

### Incidents by Service
```json
GET incidentiq-incidents/_search
{
  "size": 0,
  "aggs": {
    "by_service": {
      "terms": {
        "field": "service.keyword",
        "size": 10
      }
    }
  }
}
```

### Incidents by Error Type
```json
GET incidentiq-incidents/_search
{
  "size": 0,
  "aggs": {
    "by_error_type": {
      "terms": {
        "field": "error_type.keyword",
        "size": 20
      }
    }
  }
}
```

### Error Distribution in Logs
```json
GET logs-*/_search
{
  "size": 0,
  "query": {
    "range": {
      "@timestamp": {
        "gte": "now-1h"
      }
    }
  },
  "aggs": {
    "by_level": {
      "terms": {
        "field": "level.keyword"
      }
    },
    "by_service": {
      "terms": {
        "field": "service.keyword",
        "size": 10
      }
    }
  }
}
```

### Find Incidents with Specific Error Signature
```json
GET incidentiq-incidents/_search
{
  "query": {
    "term": {
      "error_signature": "36f5797b"
    }
  }
}
```

### Search Logs for Database Errors
```json
GET logs-*/_search
{
  "size": 10,
  "query": {
    "bool": {
      "should": [
        {"match": {"message": "database"}},
        {"match": {"message": "connection"}},
        {"match": {"message": "timeout"}}
      ],
      "minimum_should_match": 1
    }
  },
  "sort": [{"@timestamp": "desc"}]
}
```

## Index Management Queries

### List All IncidentIQ Indices
```json
GET _cat/indices/incidentiq-*,logs-*,metrics-*,baselines-*,config-*?v&s=index
```

### Check Index Mappings
```json
GET incidentiq-incidents/_mapping
```

### Check Data Stream Info
```json
GET _data_stream/logs-*
```

### Delete Test Data (USE CAREFULLY)
```json
// Delete specific incident
DELETE incidentiq-incidents/_doc/INC-001

// Delete all incidents (use with caution)
POST incidentiq-incidents/_delete_by_query
{
  "query": {
    "match_all": {}
  }
}

// Delete all runbooks (use with caution)
POST incidentiq-docs-runbooks/_delete_by_query
{
  "query": {
    "match_all": {}
  }
}
```

## ES|QL Queries

### Analyze Error Patterns
```esql
FROM incidentiq-incidents
| STATS count = COUNT(*) BY error_type, service
| SORT count DESC
```

### Calculate Average Resolution Time by Service
```esql
FROM incidentiq-incidents
| STATS avg_resolution = AVG(resolution_time_seconds) BY service
| EVAL avg_minutes = avg_resolution / 60
| SORT avg_minutes DESC
```

### Find High-Severity Incidents
```esql
FROM incidentiq-incidents
| WHERE severity == "CRITICAL" OR severity == "HIGH"
| KEEP incident_id, service, error_type, severity, resolution_time_seconds
| SORT @timestamp DESC
```

### Log Error Rate Over Time
```esql
FROM logs-*
| WHERE @timestamp > NOW() - 1 HOUR
| STATS 
    total = COUNT(*),
    errors = COUNT_IF(level == "ERROR"),
    warnings = COUNT_IF(level == "WARN")
  BY service, BUCKET(@timestamp, 5 MINUTES)
| EVAL error_rate = errors / total * 100
| SORT @timestamp DESC
```
