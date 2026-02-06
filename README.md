# IncidentIQ

Autonomous IT Operations Agent for the Elasticsearch Agent Builder Hackathon 2026

**🎯 Intelligent Incident Management System** - Complete autonomous pipeline from anomaly detection to remediation planning.

## 📊 Status

✅ **Production Ready** - Full autonomous incident management pipeline implemented

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your Elasticsearch and LLM credentials

# 3. Test connections
python test_connections.py

# 4. Run the agents
python src/detective_agent.py --once          # Detect new incidents
python src/analyst_agent.py -i INC-001        # Analyze incident 
python src/remediation_agent.py -i INC-001    # Generate remediation plan
python src/documentation_agent.py -i INC-001  # Generate documentation

# 5. Full pipeline orchestration
python src/agent_orchestrator.py -i INC-001   # Single incident pipeline
python src/agent_orchestrator.py --monitor    # Continuous monitoring

# 6. End-to-end testing
python tests/test_end_to_end.py               # Validate entire system
```

## 🏗️ Architecture

```
                            🎯 Agent Orchestrator
                                 │ (Master Controller)
                                 ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Detective Agent │───▶│ Analyst Agent   │───▶│Remediation Agent│───▶│Documentation    │
│ Anomaly         │    │ Root Cause      │    │ Workflow        │    │ Agent           │
│ Detection       │    │ Analysis        │    │ Planning        │    │ Report Gen      │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │                       │
         ▼                       ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                    Elasticsearch Cloud                                             │
│  📊 Logs    📈 Metrics    🚨 Incidents    📋 Runbooks    📄 Documentation         │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 🤖 Agent Pipeline

1. **🔍 Detective Agent** - Continuous monitoring and incident detection
2. **🔬 Analyst Agent** - Root cause analysis and workflow recommendation  
3. **🔧 Remediation Agent** - Workflow validation and execution planning
4. **📚 Documentation Agent** - Post-incident reports and runbook generation
5. **🎯 Agent Orchestrator** - Master pipeline controller coordinating all agents

## ✨ Features

- ✅ **Real-time anomaly detection** with ES|QL queries
- ✅ **Autonomous incident creation** with severity calculation
- ✅ **Similar incident search** using hybrid text + service matching
- ✅ **AI-powered root cause analysis** with Gemini/Claude
- ✅ **Workflow validation** against predefined catalog
- ✅ **Risk assessment** with auto-approval logic
- ✅ **Detailed remediation planning** with rollback procedures
- ✅ **Post-incident documentation** with markdown reports and runbook updates
- ✅ **Complete pipeline orchestration** with monitoring and error handling
- ✅ **Rich console UI** with progress indicators and tables
- ✅ **Comprehensive error handling** and graceful degradation

## 🛠️ Agent Details

### 🔍 Detective Agent (`src/detective_agent.py`)

**Purpose**: Continuous anomaly detection and incident creation

**Features**:
- ES|QL-powered anomaly detection (>5σ = CRITICAL, >3σ = HIGH, >2σ = MEDIUM)
- 5-minute deduplication window to prevent duplicate incidents
- Autonomous incident creation with INC-XXX format
- Graceful shutdown handling and statistics tracking

**Usage**:
```bash
python src/detective_agent.py                    # Run continuously
python src/detective_agent.py --once             # Single check
python src/detective_agent.py --interval 30      # 30-second intervals
```

### 🔬 Analyst Agent (`src/analyst_agent.py`)

**Purpose**: Root cause analysis and workflow recommendation

**Features**:
- Hybrid search for similar resolved incidents (text + service matching)
- ES|QL correlation analysis with time windows
- AI analysis with confidence scoring and reasoning
- Structured JSON output with workflow recommendations

**Usage**:
```bash
python src/analyst_agent.py --incident INC-001   # Analyze specific incident
python src/analyst_agent.py --incident INC-002 --quiet  # Quiet mode
```

### 🔧 Remediation Agent (`src/remediation_agent.py`)

**Purpose**: Workflow validation and remediation planning

**Features**:
- Predefined workflow catalog (5 workflows from low to high risk)
- Auto-approval logic (low risk + >70% confidence)
- Detailed execution plans with steps, validation, and rollback
- Rich workflow catalog display

**Workflow Catalog**:
| Workflow | Risk | Auto-Approve | Time |
|----------|------|--------------|------|
| `safe_service_restart` | Low | ✅ | 3min |
| `scale_pods_horizontal` | Medium | ✅ | 5min |
| `rollback_deployment` | High | ❌ | 10min |
| `investigate_dependencies` | Low | ✅ | 2min |
| `manual_intervention` | High | ❌ | 30min |

**Usage**:
```bash
python src/remediation_agent.py --incident INC-001  # Generate plan
python src/remediation_agent.py --catalog           # Show workflows
```

### 📚 Documentation Agent (`src/documentation_agent.py`)

**Purpose**: Post-incident report and runbook generation

**Features**:
- Comprehensive post-incident reports with MTTR calculations
- Runbook updates with resolution procedures
- Error type categorization and prevention strategies
- Markdown file generation with structured formatting

**Usage**:
```bash
python src/documentation_agent.py --incident INC-001    # Generate documentation
python src/documentation_agent.py --reports             # List generated reports
```

### 🎯 Agent Orchestrator (`src/agent_orchestrator.py`)

**Purpose**: Master pipeline controller coordinating all agents

**Features**:
- Single incident processing mode
- Continuous monitoring mode (polls every 30s for `status="active"`)
- Complete pipeline execution: Detective → Analyst → Remediation → Documentation
- Status tracking throughout pipeline lifecycle
- Comprehensive error handling and escalation
- Detailed statistics and operational monitoring

**Pipeline Status Flow**:
```
active → analyzing → analyzed → planning → plan_ready/approval_required → 
executing → executed → documenting → documented
```

**Usage**:
```bash
# Single incident processing
python src/agent_orchestrator.py --incident INC-001

# Continuous monitoring mode 
python src/agent_orchestrator.py --monitor --interval 30

# Show detailed statistics
python src/agent_orchestrator.py --stats

# Quiet mode for automation
python src/agent_orchestrator.py --incident INC-001 --quiet
```

## 🧪 Testing & Validation

### End-to-End Integration Test
```bash
python tests/test_end_to_end.py
```
**Validates**: Data existence, ES|QL queries, LLM client, Detective Agent, incident CRUD

**Current Results**: ✅ 5/5 tests passing

### Individual Agent Testing
```bash
python test_llm.py                    # Test LLM connectivity
python src/detective_agent.py --once  # Test anomaly detection
python test_esql_queries.py           # Test ES|QL query execution
```

## 📊 Data & Infrastructure

### Elasticsearch Cloud
- **Logs**: 7.9M+ documents across multiple services
- **Metrics**: 212K+ performance metrics and system data
- **Incidents**: 55+ historical incident records
- **Runbooks**: 8 operational runbooks and procedures

### ES|QL Queries (`tools/esql/`)
- `detect_anomalies.esql` - Statistical anomaly detection
- `correlate_root_causes.esql` - Root cause correlation analysis
- `calculate_baselines.esql` - Performance baseline calculation
- `analyze_trends.esql` - Trend analysis for capacity planning

### LLM Integration
- **Primary**: Google Gemini 2.5 Flash with quota management
- **Fallback**: Anthropic Claude 3.5 Sonnet for safety blocks
- **Features**: Rate limiting, retry logic, graceful degradation

## 🔧 Development Status

- ✅ **Infrastructure**: Elasticsearch Cloud, LLM clients, environment setup
- ✅ **Data Pipeline**: 7.9M logs, 212K metrics, comprehensive test data
- ✅ **ES|QL Queries**: Anomaly detection, correlation, baseline calculation
- ✅ **Detective Agent**: Autonomous anomaly detection and incident creation
- ✅ **Analyst Agent**: Root cause analysis and workflow recommendation
- ✅ **Remediation Agent**: Workflow validation and execution planning
- ✅ **Integration Testing**: End-to-end pipeline validation (5/5 tests)
- ✅ **Error Handling**: Comprehensive failure recovery and graceful degradation
- ✅ **SDK Migration**: Updated to google-genai for security and performance

## 🚀 Production Deployment

The system is production-ready with:
- **Autonomous Operation**: Continuous monitoring without human intervention
- **Intelligent Decision Making**: AI-powered analysis with confidence scoring
- **Risk Management**: Auto-approval for low-risk, high-confidence actions
- **Comprehensive Logging**: Full audit trail and operational visibility
- **Graceful Degradation**: Fallback procedures for all failure scenarios

## 🏆 Hackathon Achievements

Built for the **Elasticsearch Agent Builder Hackathon 2026**:

- **🎯 Complete Autonomous Pipeline**: From detection to remediation planning
- **🤖 Multi-Agent Architecture**: Three specialized autonomous agents
- **📊 Real-world Data Scale**: 7.9M+ logs, production-grade testing
- **🔍 Advanced ES|QL Usage**: Statistical anomaly detection and correlation
- **🧠 AI Integration**: Gemini/Claude with intelligent fallback logic
- **⚡ Production Ready**: Comprehensive testing and error handling

## 📜 License

Apache 2.0  
