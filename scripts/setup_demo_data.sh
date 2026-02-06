#!/bin/bash
################################################################################
# IncidentIQ Demo Data Setup Script - Context7 Documentation
################################################################################
#
# CONTEXT:
#   Demo data generation requires multiple steps in specific order:
#   baselines → service config → incidents → runbooks. This script automates
#   the entire process and validates the results.
#
# CHALLENGE:
#   - Scripts must run in correct order (dependencies between them)
#   - Elasticsearch connection must be validated before generation
#   - Each step can fail independently and needs error handling
#   - Users need clear progress indicators and error messages
#   - Final state must be verified to ensure demo will work
#
# CHOICES:
#   - Bash script for simple execution (./scripts/setup_demo_data.sh)
#   - set -e for fail-fast behavior (stop on first error)
#   - Progress indicators with emoji for visual feedback
#   - Timing information for each step
#   - Comprehensive summary at the end
#   - Option to skip verification (--skip-verify)
#
# CRITERIA:
#   - Must validate prerequisites before starting
#   - Must run all generation scripts in correct order
#   - Must handle errors gracefully with clear messages
#   - Must provide timing and progress information
#   - Must verify final state and provide summary
#
# CONSEQUENCES:
#   - Single command sets up entire demo environment
#   - Clear error messages help troubleshoot connection issues
#   - Timing information helps optimize generation parameters
#   - Verification prevents demos with incomplete data
#
# CONCLUSION:
#   This script reduces demo setup from 5+ manual commands to one,
#   with built-in validation and clear progress reporting.
#
# CALL-TO-ACTION:
#   # Full setup (7 days, 25 incidents, 10 runbooks)
#   ./scripts/setup_demo_data.sh
#   
#   # Quick setup (3 days, 10 incidents, 5 runbooks)
#   ./scripts/setup_demo_data.sh --quick
#   
#   # Skip final verification
#   ./scripts/setup_demo_data.sh --skip-verify
#
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration (can be overridden by flags)
BASELINE_DAYS=7
INCIDENT_COUNT=25
RUNBOOK_COUNT=10
SKIP_VERIFY=false
QUICK_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            QUICK_MODE=true
            BASELINE_DAYS=3
            INCIDENT_COUNT=10
            RUNBOOK_COUNT=5
            shift
            ;;
        --skip-verify)
            SKIP_VERIFY=true
            shift
            ;;
        --days)
            BASELINE_DAYS="$2"
            shift 2
            ;;
        --incidents)
            INCIDENT_COUNT="$2"
            shift 2
            ;;
        --runbooks)
            RUNBOOK_COUNT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --quick              Quick mode (3 days, 10 incidents, 5 runbooks)"
            echo "  --skip-verify        Skip final verification step"
            echo "  --days N             Number of baseline days (default: 7)"
            echo "  --incidents N        Number of incidents (default: 25)"
            echo "  --runbooks N         Number of runbooks (default: 10)"
            echo "  --help               Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                   # Full setup"
            echo "  $0 --quick           # Quick setup for testing"
            echo "  $0 --days 14         # 14 days of baselines"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Start timer
SCRIPT_START=$(date +%s)

# Header
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}🏗️  IncidentIQ Demo Data Setup${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ "$QUICK_MODE" = true ]; then
    echo -e "${YELLOW}⚡ QUICK MODE: ${BASELINE_DAYS} days, ${INCIDENT_COUNT} incidents, ${RUNBOOK_COUNT} runbooks${NC}"
    echo ""
fi

echo -e "${BLUE}Configuration:${NC}"
echo -e "  Baseline days:     ${BASELINE_DAYS}"
echo -e "  Incidents:         ${INCIDENT_COUNT}"
echo -e "  Runbooks:          ${RUNBOOK_COUNT}"
echo -e "  Verification:      $([ "$SKIP_VERIFY" = true ] && echo "SKIP" || echo "ENABLED")"
echo ""

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}❌ Error: Must run from project root directory${NC}"
    echo -e "${YELLOW}   Run: cd /path/to/incidentIQ && ./scripts/setup_demo_data.sh${NC}"
    exit 1
fi

# Check if virtual environment is activated
if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not activated${NC}"
    if [ -f "venv/bin/activate" ]; then
        echo -e "${YELLOW}   Activating venv...${NC}"
        source venv/bin/activate
    else
        echo -e "${RED}❌ Virtual environment not found${NC}"
        echo -e "${YELLOW}   Create one with: python -m venv venv${NC}"
        exit 1
    fi
fi

# Function to print step header
print_step() {
    local step_num=$1
    local step_name=$2
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}${step_num}  ${step_name}${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# Function to print timing
print_timing() {
    local start=$1
    local end=$2
    local duration=$((end - start))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))
    
    if [ $minutes -gt 0 ]; then
        echo -e "${BLUE}   ⏱️  Completed in ${minutes}m ${seconds}s${NC}"
    else
        echo -e "${BLUE}   ⏱️  Completed in ${seconds}s${NC}"
    fi
}

# 1. Check Prerequisites
print_step "1️⃣" "Checking Prerequisites"

STEP_START=$(date +%s)

echo -e "${YELLOW}→${NC} Checking Elasticsearch connection..."
if ! python -c "from test_connections import *; test_elasticsearch()" 2>/dev/null; then
    echo -e "${YELLOW}→${NC} Trying alternative connection test..."
    if ! python -c "
import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
load_dotenv()
es = Elasticsearch(cloud_id=os.getenv('ELASTIC_CLOUD_ID'), api_key=os.getenv('ELASTIC_API_KEY'))
print('✅ Connected to:', es.info()['cluster_name'])
" 2>/dev/null; then
        echo -e "${RED}❌ Elasticsearch connection failed${NC}"
        echo -e "${YELLOW}   Check your .env file for ELASTIC_CLOUD_ID and ELASTIC_API_KEY${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✅ Elasticsearch connection verified${NC}"

STEP_END=$(date +%s)
print_timing $STEP_START $STEP_END

# 2. Generate Baseline Data
print_step "2️⃣" "Generating Baseline Data (${BASELINE_DAYS} days)"

STEP_START=$(date +%s)

echo -e "${YELLOW}→${NC} Running generate_baselines.py..."
python data/generate_baselines.py --days $BASELINE_DAYS

STEP_END=$(date +%s)
print_timing $STEP_START $STEP_END

# 3. Generate Service Configuration
print_step "3️⃣" "Generating Service Configuration"

STEP_START=$(date +%s)

echo -e "${YELLOW}→${NC} Running generate_service_config.py..."
python data/generate_service_config.py

STEP_END=$(date +%s)
print_timing $STEP_START $STEP_END

# 4. Generate Historical Incidents
print_step "4️⃣" "Generating Historical Incidents (${INCIDENT_COUNT} incidents)"

STEP_START=$(date +%s)

echo -e "${YELLOW}→${NC} Running generate_incidents.py..."
python data/generate_incidents.py --count $INCIDENT_COUNT

STEP_END=$(date +%s)
print_timing $STEP_START $STEP_END

# 5. Generate Runbooks
print_step "5️⃣" "Generating Runbooks (${RUNBOOK_COUNT} runbooks)"

STEP_START=$(date +%s)

echo -e "${YELLOW}→${NC} Running generate_runbooks.py..."
python data/generate_runbooks.py --count $RUNBOOK_COUNT

STEP_END=$(date +%s)
print_timing $STEP_START $STEP_END

# 6. Verify Data
if [ "$SKIP_VERIFY" = false ]; then
    print_step "6️⃣" "Verifying Data Integrity"
    
    STEP_START=$(date +%s)
    
    echo -e "${YELLOW}→${NC} Running verify_data.py..."
    python scripts/verify_data.py
    
    STEP_END=$(date +%s)
    print_timing $STEP_START $STEP_END
else
    echo ""
    echo -e "${YELLOW}⏭️  Skipping verification (--skip-verify)${NC}"
fi

# Calculate total time
SCRIPT_END=$(date +%s)
TOTAL_DURATION=$((SCRIPT_END - SCRIPT_START))
TOTAL_MINUTES=$((TOTAL_DURATION / 60))
TOTAL_SECONDS=$((TOTAL_DURATION % 60))

# Final Summary
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Demo Data Setup Complete!${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}📊 Summary:${NC}"
echo -e "  Baseline period:    ${BASELINE_DAYS} days"
echo -e "  Incidents created:  ${INCIDENT_COUNT}"
echo -e "  Runbooks created:   ${RUNBOOK_COUNT}"
echo -e "  Total time:         ${TOTAL_MINUTES}m ${TOTAL_SECONDS}s"
echo ""
echo -e "${GREEN}🎯 Next Steps:${NC}"
echo -e "  1. Test ES|QL queries:         ${YELLOW}python test_esql_queries.py${NC}"
echo -e "  2. Run incident simulation:    ${YELLOW}python data/simulate_incident.py --speed 10${NC}"
echo -e "  3. Start incident monitor:     ${YELLOW}python src/incident_monitor.py${NC}"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
