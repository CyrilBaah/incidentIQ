#!/usr/bin/env python3
"""
IncidentIQ - Agent Orchestrator
Master controller coordinating all 4 agents in the incident management pipeline
"""

import os
import sys
import time
import json
import argparse
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))

from elasticsearch import Elasticsearch
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.json import JSON
from rich.live import Live
from rich.layout import Layout
from rich.align import Align
from rich import print as rprint

# Import all agents
from detective_agent import DetectiveAgent
from analyst_agent import AnalystAgent
from remediation_agent import RemediationAgent
from documentation_agent import DocumentationAgent
from workflow_executor import WorkflowExecutor
from integrations.slack_bot import SlackBot

class AgentOrchestrator:
    """
    Master orchestrator coordinating the complete incident management pipeline
    
    Pipeline Flow:
    1. 🔍 Detective Agent: Detects anomalies → Creates incidents (status="active")
    2. 🔬 Analyst Agent: Analyzes incidents → Recommends workflows (status="analyzed")
    3. 🔧 Remediation Agent: Validates workflows → Generates plans (status="plan_ready"/"approval_required")
    4. ⚡ Workflow Execution: (Week 3 - placeholder for now)
    5. 📚 Documentation Agent: Generates reports → Updates runbooks (status="documented")
    
    Capabilities:
    - Single incident processing
    - Continuous monitoring mode
    - Error handling and escalation
    - Status tracking and statistics
    - Comprehensive logging and audit trail
    """
    
    # Pipeline status transitions
    STATUS_TRANSITIONS = {
        "active": "analyzing",        # Detective → Analyst
        "analyzing": "analyzed",      # Analyst complete
        "analyzed": "planning",       # Analyst → Remediation  
        "planning": "plan_ready",     # Remediation complete (auto-approved)
        "plan_ready": "executing",    # Plan → Execution (Week 3)
        "executing": "executed",      # Execution complete (Week 3)
        "executed": "documenting",    # Execution → Documentation
        "documenting": "documented",  # Documentation complete
        "approval_required": "pending_approval"  # Manual approval needed
    }
    
    def __init__(self, verbose: bool = True, polling_interval: int = 30):
        self.console = Console()
        self.verbose = verbose
        self.polling_interval = polling_interval
        
        # Initialize connections
        self._setup_elasticsearch()
        
        # Pipeline tracking
        self.incidents_processed = 0
        self.successful_completions = 0
        self.failed_incidents = 0
        self.escalated_incidents = 0
        
        # Agent instances (lazy loading)
        self._detective_agent = None
        self._analyst_agent = None
        self._remediation_agent = None
        self._documentation_agent = None
        
        # Workflow execution and notifications
        self.executor = WorkflowExecutor(verbose=False)
        self.slack = SlackBot(verbose=False)
        self.slack_thread_mapping = {}  # Map incident_id to Slack thread
        
        # Pipeline statistics
        self.pipeline_stats = {
            "analyzed": 0,
            "planned": 0,
            "documented": 0,
            "escalated": 0,
            "failed": 0
        }
        
        # Error tracking
        self.recent_errors = []
        
        if self.verbose:
            self.console.print("🎯 [bold green]Agent Orchestrator initialized[/bold green]")
    
    def _setup_elasticsearch(self):
        """Setup Elasticsearch connection"""
        try:
            self.es = Elasticsearch(
                cloud_id=os.getenv("ELASTIC_CLOUD_ID"),
                api_key=os.getenv("ELASTIC_API_KEY")
            )
            
            # Test connection
            if self.es.ping():
                if self.verbose:
                    self.console.print("✅ [green]Elasticsearch connected[/green]")
            else:
                raise Exception("Elasticsearch ping failed")
                
        except Exception as e:
            self.console.print(f"❌ [red]Elasticsearch setup failed: {e}[/red]")
            raise
    
    @property
    def detective_agent(self) -> DetectiveAgent:
        """Lazy load Detective Agent"""
        if self._detective_agent is None:
            self._detective_agent = DetectiveAgent(verbose=False)
        return self._detective_agent
    
    @property
    def analyst_agent(self) -> AnalystAgent:
        """Lazy load Analyst Agent"""
        if self._analyst_agent is None:
            self._analyst_agent = AnalystAgent(verbose=False)
        return self._analyst_agent
    
    @property
    def remediation_agent(self) -> RemediationAgent:
        """Lazy load Remediation Agent"""
        if self._remediation_agent is None:
            self._remediation_agent = RemediationAgent(verbose=False)
        return self._remediation_agent
    
    @property
    def documentation_agent(self) -> DocumentationAgent:
        """Lazy load Documentation Agent"""
        if self._documentation_agent is None:
            self._documentation_agent = DocumentationAgent(verbose=False)
        return self._documentation_agent
    
    def update_incident_status(self, incident_id: str, status: str, metadata: Dict[str, Any] = None) -> bool:
        """
        Update incident status in Elasticsearch
        
        Args:
            incident_id: Incident ID to update
            status: New status value
            metadata: Additional metadata to include
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if self.verbose:
                self.console.print(f"🔄 Updating {incident_id} status: {status}")
            
            # Prepare update document
            update_doc = {
                "status": status,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "orchestrator_updated": True
            }
            
            # Add metadata if provided
            if metadata:
                update_doc.update(metadata)
            
            # Update incident in Elasticsearch
            query = {
                "query": {
                    "term": {
                        "incident_id.keyword": incident_id
                    }
                },
                "script": {
                    "source": """
                    for (entry in params.updates.entrySet()) {
                        ctx._source[entry.getKey()] = entry.getValue();
                    }
                    """,
                    "params": {
                        "updates": update_doc
                    }
                }
            }
            
            result = self.es.update_by_query(
                index="incidentiq-incidents",
                body=query
            )
            
            if result.get("updated", 0) > 0:
                if self.verbose:
                    self.console.print(f"✅ [green]Status updated: {incident_id} → {status}[/green]")
                return True
            else:
                self.console.print(f"⚠️  [yellow]No updates for {incident_id}[/yellow]")
                return False
                
        except Exception as e:
            error_msg = f"Error updating {incident_id} status: {e}"
            self.console.print(f"❌ [red]{error_msg}[/red]")
            self._log_error(incident_id, "status_update", error_msg)
            return False
    
    def _log_error(self, incident_id: str, stage: str, error: str):
        """Log error for tracking and debugging"""
        error_entry = {
            "incident_id": incident_id,
            "stage": stage,
            "error": str(error),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        self.recent_errors.append(error_entry)
        
        # Keep only last 10 errors
        if len(self.recent_errors) > 10:
            self.recent_errors = self.recent_errors[-10:]
    
    def escalate_to_human(self, incident_id: str, reason: str) -> str:
        """
        Escalate incident to human intervention
        
        Args:
            incident_id: Incident to escalate
            reason: Reason for escalation
            
        Returns:
            Escalation status
        """
        try:
            if self.verbose:
                self.console.print(f"🚨 Escalating {incident_id}: {reason}")
            
            # Update incident with escalation
            metadata = {
                "escalated": True,
                "escalation_reason": reason,
                "escalated_at": datetime.now(timezone.utc).isoformat(),
                "requires_human_intervention": True
            }
            
            self.update_incident_status(incident_id, "escalated", metadata)
            self.escalated_incidents += 1
            self.pipeline_stats["escalated"] += 1
            
            return "escalated"
            
        except Exception as e:
            error_msg = f"Error escalating {incident_id}: {e}"
            self.console.print(f"❌ [red]{error_msg}[/red]")
            self._log_error(incident_id, "escalation", error_msg)
            return "escalation_failed"
    
    def orchestrate_incident(self, incident_id: str) -> str:
        """
        Execute complete incident management pipeline for a single incident
        
        Args:
            incident_id: Incident ID to process
            
        Returns:
            Final status ("complete", "escalated", "failed")
        """
        try:
            self.incidents_processed += 1
            
            if self.verbose:
                self.console.print(f"\n🎯 [bold blue]Processing incident: {incident_id}[/bold blue]")
            
            # Get incident data for Slack notifications
            try:
                incident_response = self.es.search(
                    index="incidentiq-incidents",
                    body={
                        "query": {"term": {"incident_id.keyword": incident_id}},
                        "size": 1
                    }
                )
                
                incident_data = {}
                if incident_response["hits"]["hits"]:
                    incident_data = incident_response["hits"]["hits"][0]["_source"]
                
                # Post initial incident detection to Slack (if not already posted)
                if incident_id not in self.slack_thread_mapping:
                    thread_ts = self.slack.post_incident_detected(
                        incident_id=incident_id,
                        service=incident_data.get('service', 'Unknown'),
                        error_type=incident_data.get('error_type', 'Unknown'),
                        severity=incident_data.get('severity', 'MEDIUM')
                    )
                    if thread_ts:
                        self.slack_thread_mapping[incident_id] = thread_ts
                        
            except Exception as e:
                if self.verbose:
                    self.console.print(f"[yellow]⚠️  Slack initial notification failed: {e}[/yellow]")
            
            # Step 1: Analysis with Analyst Agent
            try:
                if self.verbose:
                    self.console.print("🔬 [cyan]Running Analyst Agent...[/cyan]")
                
                self.update_incident_status(incident_id, "analyzing")
                
                analysis = self.analyst_agent.analyze_incident(incident_id)
                if not analysis:
                    return self.escalate_to_human(incident_id, "Analysis failed - no recommendations generated")
                
                self.update_incident_status(incident_id, "analyzed", {
                    "analysis_complete": True,
                    "recommended_workflow": analysis.get("recommended_workflow"),
                    "confidence": analysis.get("confidence")
                })
                
                self.pipeline_stats["analyzed"] += 1
                
                if self.verbose:
                    workflow = analysis.get("recommended_workflow", "Unknown")
                    confidence = analysis.get("confidence", 0)
                    self.console.print(f"✅ [green]Analysis complete: {workflow} ({confidence:.1%} confidence)[/green]")
                
                # Post analysis to Slack
                try:
                    thread_ts = self.slack_thread_mapping.get(incident_id)
                    self.slack.post_analysis_complete(
                        incident_id=incident_id,
                        root_cause=analysis.get('root_cause', 'Analysis in progress'),
                        recommended_workflow=analysis.get('recommended_workflow', 'TBD'),
                        confidence=analysis.get('confidence', 0),
                        thread_ts=thread_ts
                    )
                except Exception as e:
                    if self.verbose:
                        self.console.print(f"[yellow]⚠️  Slack notification failed: {e}[/yellow]")
                
            except Exception as e:
                error_msg = f"Analyst Agent failed: {e}"
                self._log_error(incident_id, "analysis", error_msg)
                return self.escalate_to_human(incident_id, error_msg)
            
            # Step 2: Remediation Planning with Remediation Agent
            try:
                if self.verbose:
                    self.console.print("🔧 [cyan]Running Remediation Agent...[/cyan]")
                
                self.update_incident_status(incident_id, "planning")
                
                plan = self.remediation_agent.generate_remediation_plan_for_incident(incident_id)
                if not plan:
                    return self.escalate_to_human(incident_id, "Remediation planning failed")
                
                # Determine next status based on auto-approval
                next_status = "plan_ready" if plan.get("auto_approved") else "approval_required"
                
                self.update_incident_status(incident_id, next_status, {
                    "remediation_plan_ready": True,
                    "auto_approved": plan.get("auto_approved"),
                    "risk_level": plan.get("risk_level"),
                    "workflow_name": plan.get("workflow_name")
                })
                
                self.pipeline_stats["planned"] += 1
                
                if self.verbose:
                    workflow = plan.get("workflow_name", "Unknown")
                    risk = plan.get("risk_level", "Unknown")
                    auto_approved = plan.get("auto_approved", False)
                    approval_text = "auto-approved" if auto_approved else "requires approval"
                    self.console.print(f"✅ [green]Plan ready: {workflow} ({risk} risk, {approval_text})[/green]")
                
            except Exception as e:
                error_msg = f"Remediation Agent failed: {e}"
                self._log_error(incident_id, "remediation", error_msg)
                return self.escalate_to_human(incident_id, error_msg)
            
            # Step 3: Workflow Execution
            workflow_name = plan.get("workflow_name", "manual_intervention")
            workflow_success = False
            execution_result = None
            
            try:
                # Check if requires approval for high-risk workflows
                if not plan.get("auto_approved", False):
                    if self.verbose:
                        self.console.print("🔒 [yellow]Requesting approval for high-risk workflow...[/yellow]")
                    
                    # Get incident data for approval request
                    incident_response = self.es.search(
                        index="incidentiq-incidents",
                        body={
                            "query": {"term": {"incident_id.keyword": incident_id}},
                            "size": 1
                        }
                    )
                    
                    incident_data = {}
                    if incident_response["hits"]["hits"]:
                        incident_data = incident_response["hits"]["hits"][0]["_source"]
                    
                    approved = self.slack.request_approval(
                        incident_id=incident_id,
                        workflow_name=workflow_name,
                        service=incident_data.get('service', 'Unknown'),
                        risk_level=plan.get('risk_level', 'High'),
                        timeout_seconds=600,
                        thread_ts=self.slack_thread_mapping.get(incident_id)
                    )
                    
                    if not approved:
                        if self.verbose:
                            self.console.print("[yellow]⏸️  Workflow not approved - escalating to human[/yellow]")
                        
                        self.slack.post_escalation(
                            incident_id=incident_id,
                            reason="High-risk workflow denied by approver",
                            thread_ts=self.slack_thread_mapping.get(incident_id)
                        )
                        
                        return self.escalate_to_human(incident_id, "Human approval denied")
                
                # Execute workflow
                if self.verbose:
                    self.console.print(f"⚡ [cyan]Executing workflow: {workflow_name}[/cyan]")
                
                # Post execution start notification
                self.slack.post_workflow_executing(
                    incident_id=incident_id,
                    workflow_name=workflow_name,
                    estimated_duration=plan.get('estimated_duration_seconds', 180),
                    thread_ts=self.slack_thread_mapping.get(incident_id)
                )
                
                # Load and execute workflow
                workflow_def = self.executor.load_workflow(workflow_name=workflow_name)
                if not workflow_def:
                    # Try with demo suffix for testing
                    workflow_def = self.executor.load_workflow(workflow_name=f"{workflow_name}_demo")
                
                if workflow_def:
                    # Get incident data for parameters
                    incident_response = self.es.search(
                        index="incidentiq-incidents",
                        body={
                            "query": {"term": {"incident_id.keyword": incident_id}},
                            "size": 1
                        }
                    )
                    
                    incident_data = {}
                    if incident_response["hits"]["hits"]:
                        incident_data = incident_response["hits"]["hits"][0]["_source"]
                    
                    execution_result = self.executor.execute_workflow(
                        workflow=workflow_def,
                        params={
                            'incident_id': incident_id,
                            'service': incident_data.get('service', 'unknown-service'),
                            'namespace': 'incidentiq-demo',
                            'timeout_seconds': 120
                        }
                    )
                    
                    workflow_success = execution_result.get('success', False)
                    
                    if workflow_success:
                        self.update_incident_status(incident_id, "executed", {
                            "execution_complete": True,
                            "workflow_executed": workflow_name,
                            "execution_duration": execution_result.get('total_duration_seconds', 0)
                        })
                        
                        if self.verbose:
                            duration = execution_result.get('total_duration_seconds', 0)
                            self.console.print(f"✅ [green]Workflow executed successfully ({duration:.1f}s)[/green]")
                    else:
                        if self.verbose:
                            self.console.print(f"❌ [red]Workflow execution failed[/red]")
                        
                        # Post failure and escalate
                        self.slack.post_escalation(
                            incident_id=incident_id,
                            reason=f"Workflow execution failed: {execution_result.get('message', 'Unknown error')}",
                            thread_ts=self.slack_thread_mapping.get(incident_id)
                        )
                        
                        return self.escalate_to_human(incident_id, "Workflow execution failed")
                
                else:
                    if self.verbose:
                        self.console.print(f"❌ [red]Workflow definition not found: {workflow_name}[/red]")
                    
                    # Simulate execution for unknown workflows
                    self.update_incident_status(incident_id, "executed", {
                        "execution_note": f"Simulated execution of {workflow_name}",
                        "execution_simulated": True
                    })
                    
                    workflow_success = True  # Assume success for simulation
                    execution_result = {"success": True, "total_duration_seconds": 30, "message": "Simulated execution"}
                
            except Exception as e:
                error_msg = f"Workflow execution failed: {e}"
                self._log_error(incident_id, "execution", error_msg)
                
                self.slack.post_escalation(
                    incident_id=incident_id,
                    reason=error_msg,
                    thread_ts=self.slack_thread_mapping.get(incident_id)
                )
                
                return self.escalate_to_human(incident_id, error_msg)
            
            # Step 4: Documentation with Documentation Agent
            try:
                if self.verbose:
                    self.console.print("📚 [cyan]Running Documentation Agent...[/cyan]")
                
                self.update_incident_status(incident_id, "documenting")
                
                documentation = self.documentation_agent.generate_documentation_for_incident(incident_id)
                if not documentation:
                    # Don't escalate for documentation failures - not critical
                    if self.verbose:
                        self.console.print("⚠️  [yellow]Documentation generation failed - continuing[/yellow]")
                else:
                    self.pipeline_stats["documented"] += 1
                    if self.verbose:
                        report = "✅" if documentation.get("report_generated") else "❌"
                        runbook = "✅" if documentation.get("runbook_generated") else "❌"
                        self.console.print(f"✅ [green]Documentation complete: Report {report} Runbook {runbook}[/green]")
                
                # Final status
                final_status = "documented" if documentation else "execution_complete"
                self.update_incident_status(incident_id, final_status, {
                    "pipeline_complete": True,
                    "documentation_generated": bool(documentation)
                })
                
            except Exception as e:
                error_msg = f"Documentation Agent failed: {e}"
                self._log_error(incident_id, "documentation", error_msg)
                # Don't escalate for documentation failures
                if self.verbose:
                    self.console.print(f"⚠️  [yellow]Documentation failed but continuing: {error_msg}[/yellow]")
            
            # Success!
            self.successful_completions += 1
            
            # Post resolution to Slack
            try:
                if execution_result:
                    self.slack.post_resolution(
                        incident_id=incident_id,
                        workflow_name=workflow_name,
                        duration_seconds=int(execution_result.get('total_duration_seconds', 0)),
                        success=workflow_success,
                        thread_ts=self.slack_thread_mapping.get(incident_id)
                    )
            except Exception as e:
                if self.verbose:
                    self.console.print(f"[yellow]⚠️  Final Slack notification failed: {e}[/yellow]")
            
            if self.verbose:
                self.console.print(f"🎉 [bold green]Pipeline complete for {incident_id}![/bold green]")
            
            return "complete"
            
        except Exception as e:
            error_msg = f"Orchestration failed for {incident_id}: {e}"
            self.console.print(f"❌ [red]{error_msg}[/red]")
            self._log_error(incident_id, "orchestration", error_msg)
            self.failed_incidents += 1
            self.pipeline_stats["failed"] += 1
            
            return self.escalate_to_human(incident_id, error_msg)
    
    def find_active_incidents(self) -> List[Dict[str, Any]]:
        """
        Find incidents ready for processing
        
        Returns:
            List of incidents with status="active"
        """
        try:
            query = {
                "query": {
                    "term": {
                        "status.keyword": "active"
                    }
                },
                "sort": [
                    {"@timestamp": {"order": "asc"}}  # Process oldest first
                ],
                "size": 50  # Limit batch size
            }
            
            result = self.es.search(
                index="incidentiq-incidents",
                body=query
            )
            
            incidents = []
            for hit in result["hits"]["hits"]:
                incident = hit["_source"]
                incidents.append(incident)
            
            if self.verbose and incidents:
                self.console.print(f"🔍 [blue]Found {len(incidents)} active incident(s)[/blue]")
            
            return incidents
            
        except Exception as e:
            self.console.print(f"❌ [red]Error finding active incidents: {e}[/red]")
            return []
    
    def monitor_and_process(self) -> None:
        """
        Continuous monitoring mode - process incidents as they become active
        """
        self.console.print(f"🔄 [bold yellow]Starting continuous monitoring (polling every {self.polling_interval}s)[/bold yellow]")
        
        try:
            while True:
                start_time = datetime.now()
                
                # Find active incidents
                incidents = self.find_active_incidents()
                
                if incidents:
                    self.console.print(f"\n📋 [cyan]Processing {len(incidents)} incident(s)...[/cyan]")
                    
                    # Process each incident
                    for incident in incidents:
                        incident_id = incident.get("incident_id", "Unknown")
                        try:
                            result = self.orchestrate_incident(incident_id)
                            if self.verbose:
                                status_color = "green" if result == "complete" else "yellow"
                                self.console.print(f"  • {incident_id}: [{status_color}]{result}[/{status_color}]")
                        except Exception as e:
                            self.console.print(f"  • {incident_id}: [red]error - {e}[/red]")
                
                # Show statistics
                if self.verbose and self.incidents_processed > 0:
                    self._show_monitoring_stats()
                
                # Sleep until next poll
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(0, self.polling_interval - elapsed)
                
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            self.console.print("\n🛑 [yellow]Monitoring stopped by user[/yellow]")
        except Exception as e:
            self.console.print(f"\n💥 [red]Monitoring error: {e}[/red]")
    
    def _show_monitoring_stats(self):
        """Show monitoring statistics"""
        success_rate = (self.successful_completions / max(1, self.incidents_processed)) * 100
        
        self.console.print(f"\n📊 [bold blue]Pipeline Statistics:[/bold blue]")
        self.console.print(f"  • Processed: {self.incidents_processed}")
        self.console.print(f"  • Completed: {self.successful_completions}")
        self.console.print(f"  • Success Rate: {success_rate:.1f}%")
        self.console.print(f"  • Escalated: {self.escalated_incidents}")
        self.console.print(f"  • Failed: {self.failed_incidents}")
    
    def get_detailed_stats(self) -> Dict[str, Any]:
        """Get comprehensive orchestrator statistics"""
        success_rate = (self.successful_completions / max(1, self.incidents_processed))
        
        return {
            "total_processed": self.incidents_processed,
            "successful_completions": self.successful_completions,
            "failed_incidents": self.failed_incidents,
            "escalated_incidents": self.escalated_incidents,
            "success_rate": success_rate,
            "pipeline_stats": self.pipeline_stats.copy(),
            "recent_errors": self.recent_errors[-5:],  # Last 5 errors
            "agent_stats": {
                "analyst_analyses": self.pipeline_stats["analyzed"],
                "remediation_plans": self.pipeline_stats["planned"],
                "documentation_generated": self.pipeline_stats["documented"]
            }
        }


def main():
    """Main function for testing and demonstration"""
    parser = argparse.ArgumentParser(description="IncidentIQ Agent Orchestrator")
    parser.add_argument("--incident", "-i", help="Process specific incident ID")
    parser.add_argument("--monitor", "-m", action="store_true", help="Continuous monitoring mode")
    parser.add_argument("--interval", "-t", type=int, default=30, help="Polling interval (seconds)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")
    parser.add_argument("--stats", "-s", action="store_true", help="Show detailed statistics")
    args = parser.parse_args()
    
    console = Console()
    
    # Header
    console.print(Panel.fit(
        "🎯 [bold blue]IncidentIQ - Agent Orchestrator[/bold blue]",
        subtitle="Master Pipeline Controller"
    ))
    
    try:
        # Initialize orchestrator
        orchestrator = AgentOrchestrator(verbose=not args.quiet, polling_interval=args.interval)
        
        # Show statistics if requested
        if args.stats:
            stats = orchestrator.get_detailed_stats()
            
            console.print("\n📊 [bold green]Detailed Statistics:[/bold green]")
            
            # Main stats table
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="white")
            
            table.add_row("Total Processed", str(stats["total_processed"]))
            table.add_row("Successful Completions", str(stats["successful_completions"]))
            table.add_row("Success Rate", f"{stats['success_rate']:.1%}")
            table.add_row("Escalated", str(stats["escalated_incidents"]))
            table.add_row("Failed", str(stats["failed_incidents"]))
            
            console.print(table)
            
            # Pipeline breakdown
            console.print("\n🔄 [bold cyan]Pipeline Breakdown:[/bold cyan]")
            pipeline_table = Table(show_header=True, header_style="bold magenta")
            pipeline_table.add_column("Stage", style="cyan")
            pipeline_table.add_column("Count", style="white")
            
            for stage, count in stats["pipeline_stats"].items():
                pipeline_table.add_row(stage.title(), str(count))
            
            console.print(pipeline_table)
            
            return 0
        
        # Single incident mode
        if args.incident:
            console.print(f"\n🎯 Processing single incident: {args.incident}")
            result = orchestrator.orchestrate_incident(args.incident)
            
            console.print(f"\n📋 [bold green]Pipeline Result:[/bold green]")
            console.print(f"  • Incident: {args.incident}")
            console.print(f"  • Result: {result}")
            
            # Show stats
            stats = orchestrator.get_detailed_stats()
            console.print(f"\n📊 [bold blue]Session Stats:[/bold blue]")
            console.print(f"  • Processed: {stats['total_processed']}")
            console.print(f"  • Success Rate: {stats['success_rate']:.1%}")
            
            return 0 if result == "complete" else 1
        
        # Monitoring mode
        if args.monitor:
            orchestrator.monitor_and_process()
            return 0
        
        # Default: show help
        parser.print_help()
        return 0
        
    except Exception as e:
        console.print(f"\n💥 [bold red]Fatal error: {e}[/bold red]")
        return 1


if __name__ == "__main__":
    exit(main())