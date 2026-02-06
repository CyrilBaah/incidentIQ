#!/usr/bin/env python3
"""
IncidentIQ - Remediation Agent
Validates workflows and generates detailed remediation plans
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))

from elasticsearch import Elasticsearch
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.json import JSON
from rich import print as rprint

from utils.llm_client import LLMClient

class RemediationAgent:
    """
    Autonomous agent for workflow validation and remediation planning
    
    Capabilities:
    - Load incidents with proposed workflows from Analyst
    - Validate workflows against predefined catalog
    - Assess risk levels and auto-approval eligibility
    - Generate detailed remediation plans with steps
    - Create comprehensive rollback procedures
    - Update incidents with execution-ready plans
    """
    
    # Workflow Catalog - Predefined workflows with metadata
    WORKFLOW_CATALOG = {
        "safe_service_restart": {
            "risk": "low",
            "auto_approve": True,
            "time": 180,
            "description": "Graceful restart of service with health checks",
            "prerequisites": ["Service monitoring enabled", "Traffic can be rerouted"],
            "impact": "Brief service interruption (30-60 seconds)"
        },
        "scale_pods_horizontal": {
            "risk": "medium", 
            "auto_approve": True,
            "time": 300,
            "description": "Scale Kubernetes pods horizontally to handle load",
            "prerequisites": ["Kubernetes cluster available", "Resource quotas sufficient"],
            "impact": "No service interruption, increased resource usage"
        },
        "rollback_deployment": {
            "risk": "high",
            "auto_approve": False, 
            "time": 600,
            "description": "Rollback to previous deployment version",
            "prerequisites": ["Previous deployment available", "Database migrations compatible"],
            "impact": "Potential data loss, feature rollback"
        },
        "investigate_dependencies": {
            "risk": "low",
            "auto_approve": True,
            "time": 120,
            "description": "Investigate dependency health and connectivity",
            "prerequisites": ["Monitoring access", "Service topology available"],
            "impact": "No service impact, investigation only"
        },
        "manual_intervention": {
            "risk": "high",
            "auto_approve": False,
            "time": 1800,
            "description": "Manual investigation and intervention required",
            "prerequisites": ["Senior engineer available", "Incident escalation"],
            "impact": "Varies based on intervention"
        }
    }
    
    def __init__(self, verbose: bool = True):
        self.console = Console()
        self.verbose = verbose
        
        # Initialize connections
        self._setup_elasticsearch()
        self._setup_llm()
        
        # Remediation tracking
        self.plans_generated = 0
        self.auto_approved = 0
        self.manual_approval_required = 0
        
        if self.verbose:
            self.console.print("🔧 [bold green]Remediation Agent initialized[/bold green]")
    
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
    
    def _setup_llm(self):
        """Setup LLM client"""
        try:
            self.llm = LLMClient(provider="gemini", verbose=False)
            if self.verbose:
                self.console.print("✅ [green]LLM client initialized[/green]")
        except Exception as e:
            self.console.print(f"❌ [red]LLM setup failed: {e}[/red]")
            raise
    
    def load_incident_with_analysis(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """
        Load incident with analysis results from Analyst Agent
        
        Args:
            incident_id: Incident ID (e.g., "INC-001")
            
        Returns:
            Incident document with analysis or None if not found
        """
        try:
            if self.verbose:
                self.console.print(f"📥 Loading analyzed incident: {incident_id}")
            
            # Search for incident by ID
            query = {
                "query": {
                    "term": {
                        "incident_id.keyword": incident_id
                    }
                }
            }
            
            result = self.es.search(
                index="incidentiq-incidents",
                body=query
            )
            
            if result["hits"]["total"]["value"] > 0:
                incident = result["hits"]["hits"][0]["_source"]
                
                # Check if incident has been analyzed
                if incident.get("status") == "analyzed" and incident.get("recommended_workflow"):
                    if self.verbose:
                        self.console.print(f"✅ [green]Analyzed incident found: {incident.get('title', 'No title')}[/green]")
                        self.console.print(f"   Proposed workflow: {incident.get('recommended_workflow')}")
                        self.console.print(f"   Confidence: {incident.get('confidence', 0):.1%}")
                    return incident
                else:
                    self.console.print(f"⚠️  [yellow]Incident {incident_id} not analyzed yet[/yellow]")
                    return None
            else:
                self.console.print(f"❌ [red]Incident {incident_id} not found[/red]")
                return None
                
        except Exception as e:
            self.console.print(f"❌ [red]Error loading incident: {e}[/red]")
            return None
    
    def validate_workflow(self, workflow_name: str) -> Optional[Dict[str, Any]]:
        """
        Validate workflow exists in catalog
        
        Args:
            workflow_name: Name of workflow to validate
            
        Returns:
            Workflow metadata or None if invalid
        """
        try:
            if self.verbose:
                self.console.print(f"🔍 Validating workflow: {workflow_name}")
            
            if workflow_name in self.WORKFLOW_CATALOG:
                workflow = self.WORKFLOW_CATALOG[workflow_name]
                if self.verbose:
                    self.console.print(f"✅ [green]Workflow validated - Risk: {workflow['risk']}[/green]")
                return workflow
            else:
                self.console.print(f"❌ [red]Unknown workflow: {workflow_name}[/red]")
                self.console.print(f"   Available workflows: {list(self.WORKFLOW_CATALOG.keys())}")
                return None
                
        except Exception as e:
            self.console.print(f"❌ [red]Error validating workflow: {e}[/red]")
            return None
    
    def assess_risk_and_approval(
        self, 
        workflow_metadata: Dict[str, Any], 
        confidence: float
    ) -> Dict[str, Any]:
        """
        Assess risk level and determine auto-approval eligibility
        
        Args:
            workflow_metadata: Workflow catalog entry
            confidence: Analysis confidence from Analyst Agent
            
        Returns:
            Risk assessment with approval decision
        """
        try:
            if self.verbose:
                self.console.print("⚖️  Assessing risk and approval requirements...")
            
            risk_level = workflow_metadata["risk"]
            
            # Apply risk assessment rules
            auto_approved = False
            approval_reason = ""
            
            if risk_level == "low" and confidence > 0.7:
                auto_approved = True
                approval_reason = "Low risk and high confidence analysis"
                self.auto_approved += 1
            elif risk_level == "high" or confidence < 0.5:
                auto_approved = False
                approval_reason = f"High risk ({risk_level}) or low confidence ({confidence:.1%})"
                self.manual_approval_required += 1
            elif risk_level == "medium" and confidence >= 0.6:
                auto_approved = True
                approval_reason = "Medium risk with adequate confidence"
                self.auto_approved += 1
            else:
                auto_approved = False
                approval_reason = f"Medium risk with insufficient confidence ({confidence:.1%})"
                self.manual_approval_required += 1
            
            assessment = {
                "risk_level": risk_level,
                "confidence": confidence,
                "auto_approved": auto_approved,
                "approval_reason": approval_reason,
                "estimated_time": workflow_metadata["time"],
                "impact": workflow_metadata.get("impact", "Impact not specified")
            }
            
            if self.verbose:
                status = "✅ Auto-approved" if auto_approved else "⚠️  Manual approval required"
                self.console.print(f"{status} - {approval_reason}")
            
            return assessment
            
        except Exception as e:
            self.console.print(f"❌ [red]Error assessing risk: {e}[/red]")
            return {
                "risk_level": "high",
                "confidence": 0.0,
                "auto_approved": False,
                "approval_reason": f"Assessment failed: {e}",
                "estimated_time": 1800,
                "impact": "Unknown impact"
            }
    
    def generate_remediation_plan(
        self,
        incident: Dict[str, Any],
        workflow_metadata: Dict[str, Any],
        assessment: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate detailed remediation plan with execution steps
        
        Args:
            incident: Incident data
            workflow_metadata: Workflow catalog entry
            assessment: Risk assessment results
            
        Returns:
            Detailed remediation plan
        """
        try:
            if self.verbose:
                self.console.print("🤖 Generating detailed remediation plan...")
            
            # Build context for LLM
            context = {
                "incident": {
                    "id": incident.get("incident_id", ""),
                    "title": incident.get("title", ""),
                    "description": incident.get("description", ""),
                    "affected_service": incident.get("affected_service", ""),
                    "severity": incident.get("severity", ""),
                    "root_cause": incident.get("root_cause", "")
                },
                "workflow": {
                    "name": incident.get("recommended_workflow", ""),
                    "risk": workflow_metadata["risk"],
                    "description": workflow_metadata["description"],
                    "prerequisites": workflow_metadata.get("prerequisites", []),
                    "estimated_time": workflow_metadata["time"]
                },
                "assessment": assessment
            }
            
            system_prompt = """You are an expert SRE creating detailed remediation plans for incidents.

Generate a comprehensive remediation plan with:
1. Pre-execution checks and prerequisites
2. Step-by-step execution procedures
3. Validation and verification steps
4. Comprehensive rollback procedures
5. Success criteria and monitoring

Be specific, actionable, and include timing estimates. Consider the service context and risk level.

Respond with valid JSON only."""
            
            user_prompt = f"""Create a detailed remediation plan for this incident:

INCIDENT CONTEXT:
{json.dumps(context['incident'], indent=2)}

WORKFLOW DETAILS:
{json.dumps(context['workflow'], indent=2)}

RISK ASSESSMENT:
{json.dumps(context['assessment'], indent=2)}

Generate a comprehensive remediation plan with execution steps, validation procedures, and rollback plan. Include specific commands, timing estimates, and success criteria.

Respond in JSON with:
- pre_checks: Array of prerequisite validations
- execution_steps: Array of detailed execution steps with commands and timing
- validation_steps: Array of verification procedures
- rollback_plan: Array of rollback steps if execution fails
- success_criteria: Array of success indicators
- monitoring_plan: Array of monitoring checks during execution"""
            
            # Generate plan
            response = self.llm.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2,
                max_tokens=2048,
                response_format="json"
            )
            
            # Parse response
            try:
                plan = json.loads(response)
                
                # Validate required fields and add fallbacks
                required_fields = ["pre_checks", "execution_steps", "validation_steps", "rollback_plan"]
                for field in required_fields:
                    if field not in plan:
                        plan[field] = [f"AI failed to generate {field} - manual planning required"]
                
                # Add metadata
                plan["generated_at"] = datetime.now(timezone.utc).isoformat()
                plan["generator"] = "ai_remediation_agent"
                plan["workflow_name"] = incident.get("recommended_workflow", "")
                plan["risk_level"] = assessment["risk_level"]
                plan["auto_approved"] = assessment["auto_approved"]
                plan["estimated_duration"] = workflow_metadata["time"]
                
                if self.verbose:
                    steps_count = len(plan.get("execution_steps", []))
                    self.console.print(f"✅ [green]Remediation plan generated - {steps_count} execution steps[/green]")
                
                return plan
                
            except json.JSONDecodeError as e:
                self.console.print(f"⚠️  [yellow]Invalid JSON response, using fallback plan: {e}[/yellow]")
                return self._generate_fallback_plan(incident, workflow_metadata, assessment)
                
        except Exception as e:
            self.console.print(f"❌ [red]Plan generation failed: {e}[/red]")
            return self._generate_fallback_plan(incident, workflow_metadata, assessment)
    
    def _generate_fallback_plan(
        self, 
        incident: Dict[str, Any], 
        workflow_metadata: Dict[str, Any], 
        assessment: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate a basic fallback plan when AI generation fails"""
        workflow_name = incident.get("recommended_workflow", "manual_intervention")
        
        # Basic fallback plans based on workflow type
        fallback_plans = {
            "safe_service_restart": {
                "pre_checks": [
                    "Verify service health monitoring is active",
                    "Confirm traffic routing is available",
                    "Check service dependencies are healthy"
                ],
                "execution_steps": [
                    "Enable maintenance mode if available",
                    "Gracefully stop service processes",
                    "Wait 30 seconds for connections to drain",
                    "Start service processes",
                    "Verify service responds to health checks",
                    "Disable maintenance mode"
                ],
                "validation_steps": [
                    "Confirm service is responding to requests",
                    "Verify all health checks are passing",
                    "Check service metrics return to normal"
                ],
                "rollback_plan": [
                    "If service fails to start, check logs for errors",
                    "Attempt restart with previous configuration",
                    "Escalate to manual intervention if needed"
                ]
            },
            "scale_pods_horizontal": {
                "pre_checks": [
                    "Verify Kubernetes cluster connectivity",
                    "Check resource quotas and limits",
                    "Confirm horizontal pod autoscaler is configured"
                ],
                "execution_steps": [
                    "Scale deployment to increased replica count",
                    "Monitor pod creation and readiness",
                    "Verify load distribution across pods",
                    "Update monitoring thresholds if needed"
                ],
                "validation_steps": [
                    "Confirm all pods are running and ready",
                    "Verify service load is properly distributed",
                    "Check resource utilization metrics"
                ],
                "rollback_plan": [
                    "Scale back to previous replica count",
                    "Monitor for pod termination completion",
                    "Verify service stability with original scaling"
                ]
            }
        }
        
        # Get specific plan or use generic fallback
        base_plan = fallback_plans.get(workflow_name, {
            "pre_checks": ["Manual verification of prerequisites required"],
            "execution_steps": ["Manual execution required - consult runbook"],
            "validation_steps": ["Manual validation of results required"],
            "rollback_plan": ["Manual rollback procedures required"]
        })
        
        # Add metadata
        base_plan.update({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator": "fallback_remediation_agent",
            "workflow_name": workflow_name,
            "risk_level": assessment["risk_level"],
            "auto_approved": assessment["auto_approved"],
            "estimated_duration": workflow_metadata["time"],
            "success_criteria": ["Service functionality restored", "Metrics return to baseline"],
            "monitoring_plan": ["Monitor service health during execution", "Track key performance metrics"]
        })
        
        return base_plan
    
    def update_incident_with_plan(
        self, 
        incident: Dict[str, Any], 
        remediation_plan: Dict[str, Any]
    ) -> bool:
        """
        Update incident with remediation plan
        
        Args:
            incident: Original incident
            remediation_plan: Generated remediation plan
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if self.verbose:
                self.console.print("💾 Updating incident with remediation plan...")
            
            incident_id = incident.get("incident_id", "")
            
            # Prepare update document
            update_doc = {
                "remediation_plan": remediation_plan,
                "plan_generated_at": remediation_plan.get("generated_at"),
                "auto_approved": remediation_plan.get("auto_approved"),
                "estimated_duration": remediation_plan.get("estimated_duration"),
                "status": "plan_ready" if remediation_plan.get("auto_approved") else "approval_required"
            }
            
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
                    status = "plan_ready" if remediation_plan.get("auto_approved") else "approval_required"
                    self.console.print(f"✅ [green]Incident {incident_id} updated - Status: {status}[/green]")
                return True
            else:
                self.console.print(f"⚠️  [yellow]No incident updated for {incident_id}[/yellow]")
                return False
                
        except Exception as e:
            self.console.print(f"❌ [red]Error updating incident: {e}[/red]")
            return False
    
    def generate_remediation_plan_for_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """
        Complete remediation planning workflow
        
        Args:
            incident_id: ID of incident to create plan for
            
        Returns:
            Remediation plan or None if failed
        """
        try:
            self.plans_generated += 1
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                
                # Step 1: Load analyzed incident
                task = progress.add_task("Loading analyzed incident...", total=None)
                incident = self.load_incident_with_analysis(incident_id)
                if not incident:
                    return None
                
                # Step 2: Validate workflow
                progress.update(task, description="Validating workflow...")
                workflow_name = incident.get("recommended_workflow")
                workflow_metadata = self.validate_workflow(workflow_name)
                if not workflow_metadata:
                    return None
                
                # Step 3: Assess risk and approval
                progress.update(task, description="Assessing risk...")
                confidence = incident.get("confidence", 0.0)
                assessment = self.assess_risk_and_approval(workflow_metadata, confidence)
                
                # Step 4: Generate remediation plan
                progress.update(task, description="Generating remediation plan...")
                plan = self.generate_remediation_plan(incident, workflow_metadata, assessment)
                
                # Step 5: Update incident
                progress.update(task, description="Updating incident...")
                success = self.update_incident_with_plan(incident, plan)
                
                progress.update(task, description="✅ Remediation plan complete!")
            
            if success:
                return plan
            else:
                return None
                
        except Exception as e:
            self.console.print(f"❌ [red]Remediation planning workflow failed: {e}[/red]")
            return None
    
    def display_workflow_catalog(self):
        """Display the workflow catalog in a nice table"""
        table = Table(show_header=True, header_style="bold magenta", title="📋 Workflow Catalog")
        table.add_column("Workflow", style="cyan", width=20)
        table.add_column("Risk", style="yellow", width=10)
        table.add_column("Auto-Approve", style="green", width=12)
        table.add_column("Time (s)", style="blue", width=10)
        table.add_column("Description", style="white", width=40)
        
        for workflow_name, metadata in self.WORKFLOW_CATALOG.items():
            risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(metadata["risk"], "white")
            auto_approve = "✅ Yes" if metadata["auto_approve"] else "❌ No"
            
            table.add_row(
                workflow_name,
                f"[{risk_color}]{metadata['risk']}[/{risk_color}]",
                auto_approve,
                str(metadata["time"]),
                metadata["description"]
            )
        
        self.console.print(table)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics"""
        return {
            "plans_generated": self.plans_generated,
            "auto_approved": self.auto_approved,
            "manual_approval_required": self.manual_approval_required,
            "auto_approval_rate": self.auto_approved / max(1, self.plans_generated)
        }


def main():
    """Main function for testing and demonstration"""
    parser = argparse.ArgumentParser(description="IncidentIQ Remediation Agent")
    parser.add_argument("--incident", "-i", help="Incident ID to create plan for", default="INC-001")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")
    parser.add_argument("--catalog", "-c", action="store_true", help="Show workflow catalog")
    args = parser.parse_args()
    
    console = Console()
    
    # Header
    console.print(Panel.fit(
        "🔧 [bold blue]IncidentIQ - Remediation Agent[/bold blue]",
        subtitle="Workflow Validation & Remediation Planning"
    ))
    
    try:
        # Initialize agent
        agent = RemediationAgent(verbose=not args.quiet)
        
        # Show catalog if requested
        if args.catalog:
            agent.display_workflow_catalog()
            return 0
        
        # Generate remediation plan
        console.print(f"\n🎯 Creating remediation plan for: {args.incident}")
        plan = agent.generate_remediation_plan_for_incident(args.incident)
        
        if plan:
            # Display results
            console.print("\n📋 [bold green]Remediation Plan:[/bold green]")
            
            # Create summary table
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="white")
            
            table.add_row("Workflow", plan.get("workflow_name", "Unknown"))
            table.add_row("Risk Level", plan.get("risk_level", "Unknown"))
            
            auto_approved = plan.get("auto_approved", False)
            approval_status = "✅ Auto-approved" if auto_approved else "⚠️  Manual approval required"
            table.add_row("Approval Status", approval_status)
            
            duration = plan.get("estimated_duration", 0)
            table.add_row("Estimated Duration", f"{duration // 60}m {duration % 60}s")
            
            table.add_row("Execution Steps", str(len(plan.get("execution_steps", []))))
            table.add_row("Rollback Steps", str(len(plan.get("rollback_plan", []))))
            
            console.print(table)
            
            # Show execution steps
            if not args.quiet:
                console.print(f"\n🔧 [bold cyan]Execution Steps:[/bold cyan]")
                for i, step in enumerate(plan.get("execution_steps", []), 1):
                    console.print(f"  {i}. {step}")
                
                console.print(f"\n🔄 [bold yellow]Rollback Plan:[/bold yellow]")
                for i, step in enumerate(plan.get("rollback_plan", []), 1):
                    console.print(f"  {i}. {step}")
                
                # Show full JSON if very verbose
                console.print(f"\n📄 [bold cyan]Full Plan (JSON):[/bold cyan]")
                console.print(JSON(json.dumps(plan, indent=2)))
        
        # Show stats
        stats = agent.get_stats()
        console.print(f"\n📊 [bold blue]Agent Stats:[/bold blue]")
        console.print(f"  • Plans Generated: {stats['plans_generated']}")
        console.print(f"  • Auto-approved: {stats['auto_approved']}")
        console.print(f"  • Manual Approval: {stats['manual_approval_required']}")
        console.print(f"  • Auto-approval Rate: {stats['auto_approval_rate']:.1%}")
        
        if plan:
            console.print("\n✅ [bold green]Remediation plan completed successfully![/bold green]")
            return 0
        else:
            console.print("\n❌ [bold red]Remediation planning failed![/bold red]")
            return 1
            
    except Exception as e:
        console.print(f"\n💥 [bold red]Fatal error: {e}[/bold red]")
        return 1


if __name__ == "__main__":
    exit(main())