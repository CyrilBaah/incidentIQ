# IncidentIQ Scripts

This directory contains automation scripts for setting up and managing the IncidentIQ demo environment.

## Quick Start

### One-Command Setup

Generate all demo data with a single command:

```bash
# Full setup (7 days of baselines, 25 incidents, 10 runbooks)
./scripts/setup_demo_data.sh

# Quick setup for testing (3 days, 10 incidents, 5 runbooks)
./scripts/setup_demo_data.sh --quick

# Custom configuration
./scripts/setup_demo_data.sh --days 14 --incidents 50 --runbooks 15
```

This will automatically:
1. ✅ Verify Elasticsearch connection
2. 📊 Generate baseline metrics and logs
3. ⚙️ Configure service dependencies and baselines
4. 🚨 Create historical incidents
5. 📚 Generate runbooks
6. 🔍 Verify all data was created correctly

**Estimated time:**
- Quick mode: ~5-10 minutes
- Full mode: ~15-25 minutes

## Individual Scripts

### setup_demo_data.sh

Master setup script that runs all data generation steps in order.

```bash
# Full setup
./scripts/setup_demo_data.sh

# Quick mode (faster, less data)
./scripts/setup_demo_data.sh --quick

# Skip verification at end
./scripts/setup_demo_data.sh --skip-verify

# Custom parameters
./scripts/setup_demo_data.sh --days 14 --incidents 30 --runbooks 12

# Help
./scripts/setup_demo_data.sh --help
```

**Options:**
- `--quick` - Quick mode (3 days, 10 incidents, 5 runbooks)
- `--skip-verify` - Skip final verification step
- `--days N` - Number of baseline days (default: 7)
- `--incidents N` - Number of incidents to generate (default: 25)
- `--runbooks N` - Number of runbooks to generate (default: 10)
- `--help` - Show help message

### verify_data.py

Verify that all demo data has been correctly generated.

```bash
# Standard verification
python scripts/verify_data.py

# Verbose output with details
python scripts/verify_data.py --verbose

# Quick check (document counts only)
python scripts/verify_data.py --quick

# Verify 14 days of baseline data
python scripts/verify_data.py --baseline-days 14
```

**What it checks:**
- ✅ Log data (logs-*)
- ✅ Metric data (metrics-*)
- ✅ Incident data (incidentiq-incidents)
- ✅ Runbook data (incidentiq-docs-runbooks)
- ✅ Service baselines (baselines-services)
- ✅ Service dependencies (config-service-dependencies)
- ✅ Enrich policies (service_baselines, service_dependencies)

**Exit codes:**
- `0` - All verifications passed
- `1` - Verification failed (see error messages)

## Manual Data Generation

If you need to regenerate specific parts of the data:

```bash
# 1. Generate baseline data (must run first)
python data/generate_baselines.py --days 7

# 2. Generate service configuration
python data/generate_service_config.py

# 3. Generate historical incidents
python data/generate_incidents.py --count 25

# 4. Generate runbooks
python data/generate_runbooks.py --count 10

# 5. Verify everything
python scripts/verify_data.py
```

## Troubleshooting

### Connection Issues

If you see Elasticsearch connection errors:

```bash
# Test connection
python test_connections.py

# Check .env file
cat .env | grep ELASTIC

# Verify credentials are set
echo $ELASTIC_CLOUD_ID
echo $ELASTIC_API_KEY
```

### Missing Data

If verification fails:

```bash
# Re-run full setup
./scripts/setup_demo_data.sh

# Or regenerate specific components
python data/generate_baselines.py
python data/generate_service_config.py
python data/generate_incidents.py
python data/generate_runbooks.py

# Then verify
python scripts/verify_data.py --verbose
```

### Virtual Environment

Make sure you're in the virtual environment:

```bash
# Activate virtual environment
source venv/bin/activate

# Verify Python packages
pip list | grep elasticsearch
pip list | grep rich
```

### Slow Generation

If data generation is too slow:

```bash
# Use quick mode
./scripts/setup_demo_data.sh --quick

# Or reduce parameters
./scripts/setup_demo_data.sh --days 3 --incidents 10
```

## Next Steps

After successful data generation:

```bash
# 1. Test ES|QL queries
python test_esql_queries.py

# 2. Run live incident simulation
python data/simulate_incident.py --speed 10

# 3. Start the incident monitor
python src/incident_monitor.py
```

## Data Volumes

Expected document counts (7 days, 25 incidents, 10 runbooks):

| Index | Documents | Description |
|-------|-----------|-------------|
| logs-* | ~35k-1.4M | Application logs |
| metrics-* | ~7k-350k | System metrics |
| incidentiq-incidents | 25 | Historical incidents |
| incidentiq-docs-runbooks | 10 | Runbook documents |
| baselines-services | 5 | Service baselines |
| config-service-dependencies | 5 | Service dependencies |

**Quick mode** (3 days, 10 incidents, 5 runbooks):
- Logs: ~15k-600k documents
- Metrics: ~3k-150k documents
- Incidents: 10 documents
- Runbooks: 5 documents

## Advanced Usage

### CI/CD Integration

```bash
# Exit with non-zero on failure (good for CI/CD)
./scripts/setup_demo_data.sh || exit 1
python scripts/verify_data.py || exit 1
```

### Custom Time Ranges

```bash
# Generate 30 days of baseline data
python data/generate_baselines.py --days 30

# Recalculate baselines from ES data
python data/generate_service_config.py --recalculate --days 30

# Verify with correct baseline period
python scripts/verify_data.py --baseline-days 30
```

### Dry Run Mode

Test what would be generated without writing to Elasticsearch:

```bash
python data/generate_baselines.py --dry-run
python data/generate_service_config.py --dry-run
python data/generate_incidents.py --dry-run
python data/generate_runbooks.py --dry-run
```

## See Also

- [../data/README.md](../data/README.md) - Data generation scripts
- [../README.md](../README.md) - Main project README
- [../IncidentIQ-PRD-Complete.md](../IncidentIQ-PRD-Complete.md) - Product requirements
