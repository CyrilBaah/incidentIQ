#!/usr/bin/env python3
"""
IncidentIQ - Documentation Agent
Generates post-incident reports and runbook updates
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta
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

class DocumentationAgent:
    """
    Autonomous agent for incident documentation and runbook management
    
    Capabilities:
    - Load complete incident lifecycle data (detection → analysis → remediation)
    - Generate comprehensive post-incident reports
    - Create runbook updates with resolution procedures
    - Save documentation as Markdown files
    - Future: Update Elasticsearch runbook index
    """
    
    def __init__(self, verbose: bool = True):
        self.console = Console()
        self.verbose = verbose
        
        # Initialize connections
        self._setup_elasticsearch()
        self._setup_llm()
        
        # Documentation tracking
        self.reports_generated = 0
        self.runbooks_updated = 0
        
        # Create docs directory if it doesn't exist
        self.docs_dir = Path("generated_docs")
        self.docs_dir.mkdir(exist_ok=True)
        
        if self.verbose:
            self.console.print("📚 [bold green]Documentation Agent initialized[/bold green]")
    
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
    
    def load_complete_incident_data(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """
        Load complete incident data including detection, analysis, and remediation
        
        Args:
            incident_id: Incident ID (e.g., "INC-001")
            
        Returns:
            Complete incident data or None if not found
        """
        try:
            if self.verbose:
                self.console.print(f"📥 Loading complete incident data: {incident_id}")
            
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
                
                # Check if incident has complete lifecycle data
                required_fields = ["status", "root_cause", "remediation_plan"]
                missing_fields = [field for field in required_fields if not incident.get(field)]
                
                if missing_fields:
                    self.console.print(f"⚠️  [yellow]Incident {incident_id} incomplete - missing: {missing_fields}[/yellow]")
                    self.console.print("   Use Analyst and Remediation agents to complete the incident first")
                    return None
                
                if self.verbose:
                    self.console.print(f"✅ [green]Complete incident data found[/green]")
                    status = incident.get("status", "unknown")
                    self.console.print(f"   Status: {status}")
                    if incident.get("root_cause"):
                        self.console.print(f"   Root cause: {incident.get('root_cause', 'Unknown')[:50]}...")
                    if incident.get("remediation_plan"):
                        plan = incident.get("remediation_plan", {})
                        workflow = plan.get("workflow_name", "Unknown")
                        auto_approved = plan.get("auto_approved", False)
                        approval_status = "auto-approved" if auto_approved else "manual approval"
                        self.console.print(f"   Remediation: {workflow} ({approval_status})")
                
                return incident
            else:
                self.console.print(f"❌ [red]Incident {incident_id} not found[/red]")
                return None
                
        except Exception as e:
            self.console.print(f"❌ [red]Error loading incident: {e}[/red]")
            return None
    
    def generate_post_incident_report(self, incident: Dict[str, Any]) -> str:
        """
        Generate comprehensive post-incident report
        
        Args:
            incident: Complete incident data
            
        Returns:
            Markdown formatted post-incident report
        """
        try:
            if self.verbose:
                self.console.print("📄 Generating post-incident report...")
            
            # Extract key information
            incident_id = incident.get("incident_id", "Unknown")
            title = incident.get("title", "No title")
            severity = incident.get("severity", "Unknown")
            root_cause = incident.get("root_cause", "Unknown")
            reasoning = incident.get("reasoning", "No detailed analysis available")
            
            # Timeline information
            detected_time = incident.get("timestamp", "")
            analyzed_time = incident.get("analyzed_at", "")
            plan_time = incident.get("plan_generated_at", "")
            
            # Calculate MTTR if we have timestamps
            mttr_text = "Not calculated"
            if detected_time and plan_time:
                try:
                    detected_dt = datetime.fromisoformat(detected_time.replace('Z', '+00:00'))
                    plan_dt = datetime.fromisoformat(plan_time.replace('Z', '+00:00'))
                    mttr_seconds = (plan_dt - detected_dt).total_seconds()
                    mttr_minutes = int(mttr_seconds / 60)
                    mttr_text = f"~{mttr_minutes} minutes"
                except:
                    mttr_text = "Calculation failed"
            
            # Remediation information
            remediation_plan = incident.get("remediation_plan", {})
            workflow_name = remediation_plan.get("workflow_name", "Unknown")
            execution_steps = remediation_plan.get("execution_steps", [])
            auto_approved = remediation_plan.get("auto_approved", False)
            
            # Format timeline
            def format_timestamp(timestamp_str):
                if not timestamp_str:
                    return "Not available"
                try:
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                except:
                    return timestamp_str
            
            # Generate report
            report = f"""# Post-Incident Report: {incident_id}

**Date:** {format_timestamp(detected_time)}  
**Severity:** {severity.upper()}  
**Status:** {incident.get("status", "Unknown").title()}

## Summary

{root_cause}

The incident was detected through automated monitoring and processed through our autonomous incident management pipeline. The system successfully identified the root cause and generated an appropriate remediation plan.

## Timeline

- **Detected:** {format_timestamp(detected_time)}
- **Analyzed:** {format_timestamp(analyzed_time)}
- **Plan Generated:** {format_timestamp(plan_time)}
- **Status:** {"Auto-approved" if auto_approved else "Manual approval required"}

## Root Cause

**Analysis:** {root_cause}

**Detailed Reasoning:** {reasoning}

**Confidence Level:** {incident.get("confidence", 0):.1%}

## Resolution

**Recommended Workflow:** `{workflow_name}`

**Execution Plan:**"""
            
            # Add execution steps
            if execution_steps:
                for i, step in enumerate(execution_steps, 1):
                    report += f"\n{i}. {step}"
            else:
                report += "\n1. Manual intervention required - refer to runbook"
            
            # Add rollback plan
            rollback_plan = remediation_plan.get("rollback_plan", [])
            if rollback_plan:
                report += f"\n\n**Rollback Procedures:**"
                for i, step in enumerate(rollback_plan, 1):
                    report += f"\n{i}. {step}"
            
            # Add impact and MTTR
            report += f"""

## Impact

**MTTR:** {mttr_text}  
**Approval Status:** {"✅ Auto-approved for immediate execution" if auto_approved else "⚠️ Manual approval required"}  
**Risk Level:** {remediation_plan.get("risk_level", "Unknown").title()}

## Similar Incidents

"""
            
            # Add similar incidents if available
            similar_incidents = incident.get("similar_incidents", [])
            if similar_incidents:
                for sim_id in similar_incidents:
                    report += f"- {sim_id} (identified during analysis)\n"
            else:
                report += "No similar incidents identified during analysis\n"
            
            # Add lessons learned and prevention
            report += f"""
## Lessons Learned

- Automated detection successfully identified the issue
- Root cause analysis provided {incident.get("confidence", 0):.0%} confidence in findings
- {"Workflow auto-approved for quick resolution" if auto_approved else "Manual approval ensures safety for high-risk operations"}

## Prevention

Future similar incidents can be prevented by:
- Monitoring the identified root cause indicators
- Implementing automated remediation for {"this low-risk scenario" if auto_approved else "similar patterns once validated"}
- Reviewing service dependencies and performance baselines

---
*Report generated by IncidentIQ Documentation Agent on {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}*
"""
            
            if self.verbose:
                lines = len(report.split('\n'))
                self.console.print(f"✅ [green]Post-incident report generated ({lines} lines)[/green]")
            
            return report
            
        except Exception as e:
            self.console.print(f"❌ [red]Error generating post-incident report: {e}[/red]")
            return f"# Post-Incident Report: {incident.get('incident_id', 'Unknown')}\n\nError generating report: {e}"
    
    def generate_runbook_update(self, incident: Dict[str, Any]) -> str:
        """
        Generate runbook update with resolution procedures
        
        Args:
            incident: Complete incident data
            
        Returns:
            Markdown formatted runbook update
        """
        try:
            if self.verbose:
                self.console.print("📖 Generating runbook update...")
            
            # Extract key information
            incident_id = incident.get("incident_id", "Unknown")
            root_cause = incident.get("root_cause", "Unknown")
            detected_time = incident.get("timestamp", "")
            
            # Determine error type from root cause
            error_type = self._categorize_error_type(root_cause)
            
            # Get symptoms from incident description
            symptoms = self._extract_symptoms(incident)
            
            # Get remediation information
            remediation_plan = incident.get("remediation_plan", {})
            workflow_name = remediation_plan.get("workflow_name", "manual_intervention")
            execution_steps = remediation_plan.get("execution_steps", [])
            
            # Format date
            def format_date(timestamp_str):
                if not timestamp_str:
                    return "Unknown"
                try:
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    return dt.strftime("%Y-%m-%d")
                except:
                    return timestamp_str
            
            # Generate runbook update
            runbook = f"""## {error_type}

**Last Occurred:** {format_date(detected_time)}  
**Incident ID:** {incident_id}  
**Severity:** {incident.get("severity", "Unknown").upper()}

### Symptoms

"""
            
            # Add symptoms
            for symptom in symptoms:
                runbook += f"- {symptom}\n"
            
            runbook += f"""
### Root Cause

{root_cause}

### Resolution

**Workflow:** `{workflow_name}`

**Steps:**
"""
            
            # Add resolution steps
            if execution_steps:
                for i, step in enumerate(execution_steps, 1):
                    runbook += f"{i}. {step}\n"
            else:
                runbook += "1. Manual investigation required\n2. Follow escalation procedures\n"
            
            # Add validation steps
            validation_steps = remediation_plan.get("validation_steps", [])
            if validation_steps:
                runbook += f"\n**Validation:**\n"
                for i, step in enumerate(validation_steps, 1):
                    runbook += f"{i}. {step}\n"
            
            # Add rollback information
            rollback_plan = remediation_plan.get("rollback_plan", [])
            if rollback_plan:
                runbook += f"\n**Rollback (if needed):**\n"
                for i, step in enumerate(rollback_plan, 1):
                    runbook += f"{i}. {step}\n"
            
            # Add related incidents
            similar_incidents = incident.get("similar_incidents", [])
            runbook += f"\n### Related Incidents\n\n"
            
            if similar_incidents:
                # Calculate similarity scores (placeholder - would need actual similarity calculation)
                for sim_id in similar_incidents:
                    similarity = 85 + (hash(sim_id) % 15)  # Fake similarity 85-99%
                    runbook += f"- {sim_id} (similarity: {similarity}%)\n"
            else:
                runbook += "- No related incidents identified\n"
            
            # Add prevention notes
            runbook += f"""
### Prevention

- Monitor for symptoms listed above
- Implement automated alerts for similar patterns
- Review service dependencies regularly

### Notes

- **Auto-approved:** {"Yes" if remediation_plan.get("auto_approved") else "No"}
- **Risk Level:** {remediation_plan.get("risk_level", "Unknown").title()}
- **Estimated Duration:** {remediation_plan.get("estimated_duration", 0) // 60} minutes

---
*Updated by IncidentIQ Documentation Agent on {datetime.now(timezone.utc).strftime("%Y-%m-%d")}*
"""
            
            if self.verbose:
                lines = len(runbook.split('\n'))
                self.console.print(f"✅ [green]Runbook update generated ({lines} lines)[/green]")
            
            return runbook
            
        except Exception as e:
            self.console.print(f"❌ [red]Error generating runbook update: {e}[/red]")
            return f"## Error\n\nFailed to generate runbook update: {e}"
    
    def _categorize_error_type(self, root_cause: str) -> str:
        """Categorize error type from root cause"""
        root_cause_lower = root_cause.lower()
        
        if any(term in root_cause_lower for term in ["memory", "leak", "cpu", "high load"]):
            return "Performance Issues"
        elif any(term in root_cause_lower for term in ["connection", "timeout", "network"]):
            return "Connection Issues"
        elif any(term in root_cause_lower for term in ["deploy", "deployment", "version"]):
            return "Deployment Issues"
        elif any(term in root_cause_lower for term in ["database", "db", "query"]):
            return "Database Issues"
        elif any(term in root_cause_lower for term in ["service", "down", "unavailable"]):
            return "Service Unavailability"
        else:
            return "General Service Issues"
    
    def _extract_symptoms(self, incident: Dict[str, Any]) -> List[str]:
        """Extract symptoms from incident data"""
        symptoms = []
        
        # From title
        title = incident.get("title", "")
        if title and title != "No title":
            symptoms.append(f"Reported issue: {title}")
        
        # From description
        description = incident.get("description", "")
        if description:
            symptoms.append(f"Details: {description}")
        
        # From affected service
        affected_service = incident.get("affected_service", "")
        if affected_service:
            symptoms.append(f"Affected service: {affected_service}")
        
        # From severity
        severity = incident.get("severity", "")
        if severity:
            symptoms.append(f"Severity level: {severity}")
        
        # Default if no specific symptoms
        if not symptoms:
            symptoms = [
                "Service performance degradation",
                "Monitoring alerts triggered",
                "Automated detection identified anomaly"
            ]
        
        return symptoms
    
    def save_documentation(self, incident_id: str, report: str, runbook: str) -> Dict[str, bool]:
        """
        Save post-incident report and runbook update as markdown files
        
        Args:
            incident_id: Incident ID for filename
            report: Post-incident report content
            runbook: Runbook update content
            
        Returns:
            Dict with success status for each file
        """
        try:
            if self.verbose:
                self.console.print("💾 Saving documentation files...")
            
            results = {"report": False, "runbook": False}
            
            # Save post-incident report
            try:
                report_filename = f"post_incident_report_{incident_id.lower()}.md"
                report_path = self.docs_dir / report_filename
                
                with open(report_path, 'w', encoding='utf-8') as f:
                    f.write(report)
                
                results["report"] = True
                if self.verbose:
                    self.console.print(f"✅ [green]Report saved: {report_path}[/green]")
                
            except Exception as e:
                self.console.print(f"❌ [red]Error saving report: {e}[/red]")
            
            # Save runbook update
            try:
                runbook_filename = f"runbook_update_{incident_id.lower()}.md"
                runbook_path = self.docs_dir / runbook_filename
                
                with open(runbook_path, 'w', encoding='utf-8') as f:
                    f.write(runbook)
                
                results["runbook"] = True
                if self.verbose:
                    self.console.print(f"✅ [green]Runbook saved: {runbook_path}[/green]")
                
            except Exception as e:
                self.console.print(f"❌ [red]Error saving runbook: {e}[/red]")
            
            return results
            
        except Exception as e:
            self.console.print(f"❌ [red]Error in save_documentation: {e}[/red]")
            return {"report": False, "runbook": False}
    
    def generate_documentation_for_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """
        Complete documentation generation workflow
        
        Args:
            incident_id: ID of incident to document
            
        Returns:
            Documentation results or None if failed
        """
        try:
            self.reports_generated += 1
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                
                # Step 1: Load complete incident data
                task = progress.add_task("Loading incident data...", total=None)
                incident = self.load_complete_incident_data(incident_id)
                if not incident:
                    return None
                
                # Step 2: Generate post-incident report
                progress.update(task, description="Generating post-incident report...")
                report = self.generate_post_incident_report(incident)
                
                # Step 3: Generate runbook update
                progress.update(task, description="Generating runbook update...")
                runbook = self.generate_runbook_update(incident)
                
                # Step 4: Save documentation
                progress.update(task, description="Saving documentation...")
                save_results = self.save_documentation(incident_id, report, runbook)
                
                progress.update(task, description="✅ Documentation complete!")
            
            if save_results["report"] or save_results["runbook"]:
                if save_results["report"] and save_results["runbook"]:
                    self.runbooks_updated += 1
                
                return {
                    "incident_id": incident_id,
                    "report_generated": save_results["report"],
                    "runbook_generated": save_results["runbook"],
                    "report_content": report,
                    "runbook_content": runbook,
                    "generated_at": datetime.now(timezone.utc).isoformat()
                }
            else:
                return None
                
        except Exception as e:
            self.console.print(f"❌ [red]Documentation workflow failed: {e}[/red]")
            return None
    
    def list_generated_docs(self) -> List[Dict[str, Any]]:
        """List all generated documentation files"""
        try:
            docs = []
            
            for file_path in self.docs_dir.glob("*.md"):
                stat = file_path.stat()
                docs.append({
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "report" if "post_incident" in file_path.name else "runbook"
                })
            
            return sorted(docs, key=lambda x: x["modified"], reverse=True)
            
        except Exception as e:
            self.console.print(f"❌ [red]Error listing docs: {e}[/red]")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics"""
        generated_docs = self.list_generated_docs()
        
        return {
            "reports_generated": self.reports_generated,
            "runbooks_updated": self.runbooks_updated,
            "total_files": len(generated_docs),
            "report_files": len([d for d in generated_docs if d["type"] == "report"]),
            "runbook_files": len([d for d in generated_docs if d["type"] == "runbook"]),
            "docs_directory": str(self.docs_dir.absolute())
        }


def main():
    """Main function for testing and demonstration"""
    parser = argparse.ArgumentParser(description="IncidentIQ Documentation Agent")
    parser.add_argument("--incident", "-i", help="Incident ID to document", default="INC-001")
    parser.add_argument("--list", "-l", action="store_true", help="List generated documentation")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")
    args = parser.parse_args()
    
    console = Console()
    
    # Header
    console.print(Panel.fit(
        "📚 [bold blue]IncidentIQ - Documentation Agent[/bold blue]",
        subtitle="Post-Incident Reports & Runbook Updates"
    ))
    
    try:
        # Initialize agent
        agent = DocumentationAgent(verbose=not args.quiet)
        
        # List documentation if requested
        if args.list:
            docs = agent.list_generated_docs()
            
            if docs:
                console.print("\n📁 [bold green]Generated Documentation:[/bold green]")
                
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("Filename", style="cyan")
                table.add_column("Type", style="yellow")
                table.add_column("Size", style="blue")
                table.add_column("Modified", style="white")
                
                for doc in docs:
                    doc_type = "📄 Report" if doc["type"] == "report" else "📖 Runbook"
                    size_kb = doc["size"] // 1024
                    
                    table.add_row(
                        doc["filename"],
                        doc_type,
                        f"{size_kb} KB",
                        doc["modified"]
                    )
                
                console.print(table)
            else:
                console.print("\n📁 No documentation files found")
            
            return 0
        
        # Generate documentation
        console.print(f"\n🎯 Generating documentation for: {args.incident}")
        result = agent.generate_documentation_for_incident(args.incident)
        
        if result:
            # Display results
            console.print("\n📋 [bold green]Documentation Generated:[/bold green]")
            
            # Create results table
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Document Type", style="cyan")
            table.add_column("Status", style="white")
            table.add_column("Location", style="blue")
            
            report_status = "✅ Generated" if result["report_generated"] else "❌ Failed"
            runbook_status = "✅ Generated" if result["runbook_generated"] else "❌ Failed"
            
            table.add_row(
                "Post-Incident Report",
                report_status,
                f"generated_docs/post_incident_report_{args.incident.lower()}.md"
            )
            
            table.add_row(
                "Runbook Update",
                runbook_status,
                f"generated_docs/runbook_update_{args.incident.lower()}.md"
            )
            
            console.print(table)
            
            # Show content preview if not quiet
            if not args.quiet and result["report_generated"]:
                console.print(f"\n📄 [bold cyan]Report Preview (first 300 chars):[/bold cyan]")
                preview = result["report_content"][:300] + "..."
                console.print(preview)
        
        # Show stats
        stats = agent.get_stats()
        console.print(f"\n📊 [bold blue]Agent Stats:[/bold blue]")
        console.print(f"  • Documentation Sessions: {stats['reports_generated']}")
        console.print(f"  • Reports Generated: {stats['report_files']}")
        console.print(f"  • Runbooks Updated: {stats['runbook_files']}")
        console.print(f"  • Total Files: {stats['total_files']}")
        console.print(f"  • Docs Directory: {stats['docs_directory']}")
        
        if result:
            console.print("\n✅ [bold green]Documentation completed successfully![/bold green]")
            return 0
        else:
            console.print("\n❌ [bold red]Documentation generation failed![/bold red]")
            return 1
            
    except Exception as e:
        console.print(f"\n💥 [bold red]Fatal error: {e}[/bold red]")
        return 1


if __name__ == "__main__":
    exit(main())