#!/usr/bin/env python3
"""
IncidentIQ - Analyst Agent
Analyzes incidents to find root causes and recommend workflows
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

class AnalystAgent:
    """
    Autonomous agent for incident analysis and root cause determination
    
    Capabilities:
    - Load incidents from Elasticsearch
    - Find similar past incidents using hybrid search
    - Correlate root causes using ES|QL
    - Generate AI analysis with Gemini
    - Update incidents with findings
    """
    
    def __init__(self, verbose: bool = True):
        self.console = Console()
        self.verbose = verbose
        
        # Initialize connections
        self._setup_elasticsearch()
        self._setup_llm()
        self._load_esql_queries()
        
        # Analysis tracking
        self.analyses_performed = 0
        self.successful_analyses = 0
        
        if self.verbose:
            self.console.print("🔬 [bold green]Analyst Agent initialized[/bold green]")
    
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
    
    def _load_esql_queries(self):
        """Load ES|QL query templates"""
        try:
            query_path = Path("tools/esql/correlate_root_causes.esql")
            if query_path.exists():
                with open(query_path, "r") as f:
                    self.correlate_query = f.read()
                if self.verbose:
                    self.console.print("✅ [green]ES|QL queries loaded[/green]")
            else:
                self.console.print("⚠️  [yellow]correlate_root_causes.esql not found, using fallback[/yellow]")
                self.correlate_query = """
                FROM logs-*
                | WHERE @timestamp > NOW() - 1h
                | STATS count = COUNT() BY service, error_type
                | SORT count DESC
                | LIMIT 10
                """
        except Exception as e:
            self.console.print(f"⚠️  [yellow]Query loading failed: {e}[/yellow]")
            # Fallback query
            self.correlate_query = """
            FROM logs-*
            | WHERE @timestamp > NOW() - 1h  
            | STATS count = COUNT() BY service
            | SORT count DESC
            | LIMIT 5
            """
    
    def load_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """
        Load incident from Elasticsearch
        
        Args:
            incident_id: Incident ID (e.g., "INC-042")
            
        Returns:
            Incident document or None if not found
        """
        try:
            if self.verbose:
                self.console.print(f"📥 Loading incident: {incident_id}")
            
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
                if self.verbose:
                    self.console.print(f"✅ [green]Incident found: {incident.get('title', 'No title')}[/green]")
                return incident
            else:
                self.console.print(f"❌ [red]Incident {incident_id} not found[/red]")
                return None
                
        except Exception as e:
            self.console.print(f"❌ [red]Error loading incident: {e}[/red]")
            return None
    
    def find_similar_incidents(self, incident: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Find similar past incidents using hybrid search
        
        Args:
            incident: Current incident to analyze
            
        Returns:
            List of similar resolved incidents
        """
        try:
            if self.verbose:
                self.console.print("🔍 Searching for similar incidents...")
            
            # Extract key terms from incident
            title = incident.get("title", "")
            description = incident.get("description", "")
            affected_service = incident.get("affected_service", "")
            
            # Hybrid search query - text + service matching
            query = {
                "query": {
                    "bool": {
                        "should": [
                            # Text similarity
                            {
                                "multi_match": {
                                    "query": f"{title} {description}",
                                    "fields": ["title^2", "description", "tags"],
                                    "type": "best_fields",
                                    "minimum_should_match": "30%"
                                }
                            },
                            # Service exact match (higher weight)
                            {
                                "term": {
                                    "affected_service.keyword": {
                                        "value": affected_service,
                                        "boost": 3.0
                                    }
                                }
                            },
                            # Status filter - only resolved incidents
                            {
                                "term": {
                                    "status.keyword": "resolved"
                                }
                            }
                        ],
                        "filter": [
                            # Exclude current incident
                            {
                                "bool": {
                                    "must_not": {
                                        "term": {
                                            "incident_id.keyword": incident.get("incident_id", "")
                                        }
                                    }
                                }
                            }
                        ]
                    }
                },
                "size": 5
            }
            
            result = self.es.search(
                index="incidentiq-incidents",
                body=query
            )
            
            similar_incidents = []
            for hit in result["hits"]["hits"]:
                similar_incident = hit["_source"]
                similar_incident["_score"] = hit["_score"]
                similar_incidents.append(similar_incident)
            
            if self.verbose:
                self.console.print(f"✅ [green]Found {len(similar_incidents)} similar incidents[/green]")
                
            return similar_incidents
            
        except Exception as e:
            self.console.print(f"❌ [red]Error finding similar incidents: {e}[/red]")
            return []
    
    def correlate_root_causes(self, incident: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Run ES|QL correlation to find root cause patterns
        
        Args:
            incident: Incident to analyze
            
        Returns:
            Correlation results from ES|QL
        """
        try:
            if self.verbose:
                self.console.print("📊 Running root cause correlation...")
            
            # Customize query with incident details
            affected_service = incident.get("affected_service", "")
            incident_time = incident.get("timestamp", "")
            
            # Build time range around incident
            if incident_time:
                time_filter = f"| WHERE @timestamp >= \"{incident_time}\" - 30m AND @timestamp <= \"{incident_time}\" + 30m"
            else:
                time_filter = "| WHERE @timestamp > NOW() - 1h"
            
            # Add service filter if available
            service_filter = ""
            if affected_service:
                service_filter = f"| WHERE service == \"{affected_service}\""
            
            # Customize the base query
            custom_query = self.correlate_query.replace(
                "WHERE @timestamp > NOW() - 1h",
                f"{time_filter}{service_filter}"
            )
            
            # Execute ES|QL query
            result = self.es.esql.query(body={"query": custom_query})
            
            correlation_data = []
            if result.get("values"):
                columns = result.get("columns", [])
                for row in result["values"]:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        row_dict[col["name"]] = row[i] if i < len(row) else None
                    correlation_data.append(row_dict)
            
            if self.verbose:
                self.console.print(f"✅ [green]Found {len(correlation_data)} correlation patterns[/green]")
                
            return correlation_data
            
        except Exception as e:
            self.console.print(f"⚠️  [yellow]Correlation query failed: {e}[/yellow]")
            # Return empty results for graceful degradation
            return []
    
    def generate_analysis(
        self, 
        incident: Dict[str, Any], 
        similar_incidents: List[Dict[str, Any]], 
        correlation_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate AI analysis with Gemini
        
        Args:
            incident: Current incident
            similar_incidents: Similar past incidents
            correlation_data: Root cause correlation results
            
        Returns:
            Analysis results with root cause and recommendations
        """
        try:
            if self.verbose:
                self.console.print("🤖 Generating AI analysis...")
            
            # Build context for LLM
            context = {
                "incident": {
                    "id": incident.get("incident_id", ""),
                    "title": incident.get("title", ""),
                    "description": incident.get("description", ""),
                    "affected_service": incident.get("affected_service", ""),
                    "severity": incident.get("severity", ""),
                    "timestamp": incident.get("timestamp", "")
                },
                "similar_incidents": [
                    {
                        "id": sim.get("incident_id", ""),
                        "title": sim.get("title", ""),
                        "root_cause": sim.get("root_cause", ""),
                        "resolution": sim.get("resolution", ""),
                        "score": sim.get("_score", 0)
                    }
                    for sim in similar_incidents[:3]  # Top 3
                ],
                "correlation_data": correlation_data[:10]  # Top 10 patterns
            }
            
            system_prompt = """You are an expert SRE analyzing incidents to determine root causes and recommend workflows.

Use the provided incident details, similar past incidents, and correlation data to:
1. Identify the most likely root cause
2. Recommend an appropriate workflow
3. Assess your confidence level
4. Provide clear reasoning

Available workflows: safe_service_restart, rollback_deployment, scale_resources, investigate_dependencies, manual_intervention

Respond with valid JSON only."""
            
            user_prompt = f"""Analyze this incident:

CURRENT INCIDENT:
{json.dumps(context['incident'], indent=2)}

SIMILAR PAST INCIDENTS:
{json.dumps(context['similar_incidents'], indent=2)}

CORRELATION DATA:
{json.dumps(context['correlation_data'], indent=2)}

Determine root cause and recommend workflow. Respond in JSON with: root_cause, recommended_workflow, confidence, reasoning, similar_incidents (list of IDs)"""
            
            # Generate analysis
            response = self.llm.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=1024,
                response_format="json"
            )
            
            # Parse response
            try:
                analysis = json.loads(response)
                
                # Validate required fields
                required_fields = ["root_cause", "recommended_workflow", "confidence", "reasoning"]
                for field in required_fields:
                    if field not in analysis:
                        analysis[field] = f"Unknown {field}"
                
                # Add metadata
                analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
                analysis["analyst"] = "ai_analyst_agent"
                analysis["similar_incidents"] = [sim.get("incident_id", "") for sim in similar_incidents[:3]]
                
                if self.verbose:
                    self.console.print(f"✅ [green]Analysis generated - Root cause: {analysis.get('root_cause', 'Unknown')}[/green]")
                
                return analysis
                
            except json.JSONDecodeError as e:
                self.console.print(f"⚠️  [yellow]Invalid JSON response, using fallback: {e}[/yellow]")
                return {
                    "root_cause": "Analysis parsing failed",
                    "recommended_workflow": "manual_intervention", 
                    "confidence": 0.1,
                    "reasoning": f"JSON parsing error: {e}",
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "analyst": "ai_analyst_agent",
                    "similar_incidents": [sim.get("incident_id", "") for sim in similar_incidents[:3]]
                }
                
        except Exception as e:
            self.console.print(f"❌ [red]Analysis generation failed: {e}[/red]")
            return {
                "root_cause": "Analysis failed",
                "recommended_workflow": "manual_intervention",
                "confidence": 0.0,
                "reasoning": f"Error: {str(e)}",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "analyst": "ai_analyst_agent",
                "similar_incidents": []
            }
    
    def update_incident(self, incident: Dict[str, Any], analysis: Dict[str, Any]) -> bool:
        """
        Update incident with analysis results
        
        Args:
            incident: Original incident
            analysis: Analysis results to add
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if self.verbose:
                self.console.print("💾 Updating incident with analysis...")
            
            incident_id = incident.get("incident_id", "")
            
            # Prepare update document
            update_doc = {
                "root_cause": analysis.get("root_cause"),
                "recommended_workflow": analysis.get("recommended_workflow"),
                "confidence": analysis.get("confidence"),
                "reasoning": analysis.get("reasoning"),
                "similar_incidents": analysis.get("similar_incidents", []),
                "analyzed_at": analysis.get("analyzed_at"),
                "analyst": analysis.get("analyst"),
                "status": "analyzed"  # Update status to indicate analysis complete
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
                    self.console.print(f"✅ [green]Incident {incident_id} updated successfully[/green]")
                return True
            else:
                self.console.print(f"⚠️  [yellow]No incident updated for {incident_id}[/yellow]")
                return False
                
        except Exception as e:
            self.console.print(f"❌ [red]Error updating incident: {e}[/red]")
            return False
    
    def analyze_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """
        Complete incident analysis workflow
        
        Args:
            incident_id: ID of incident to analyze
            
        Returns:
            Analysis results or None if failed
        """
        try:
            self.analyses_performed += 1
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                
                # Step 1: Load incident
                task = progress.add_task("Loading incident...", total=None)
                incident = self.load_incident(incident_id)
                if not incident:
                    return None
                
                # Step 2: Find similar incidents
                progress.update(task, description="Finding similar incidents...")
                similar_incidents = self.find_similar_incidents(incident)
                
                # Step 3: Correlate root causes
                progress.update(task, description="Correlating root causes...")
                correlation_data = self.correlate_root_causes(incident)
                
                # Step 4: Generate analysis
                progress.update(task, description="Generating AI analysis...")
                analysis = self.generate_analysis(incident, similar_incidents, correlation_data)
                
                # Step 5: Update incident
                progress.update(task, description="Updating incident...")
                success = self.update_incident(incident, analysis)
                
                progress.update(task, description="✅ Analysis complete!")
            
            if success:
                self.successful_analyses += 1
                return analysis
            else:
                return None
                
        except Exception as e:
            self.console.print(f"❌ [red]Analysis workflow failed: {e}[/red]")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics"""
        return {
            "analyses_performed": self.analyses_performed,
            "successful_analyses": self.successful_analyses,
            "success_rate": self.successful_analyses / max(1, self.analyses_performed)
        }


def main():
    """Main function for testing and demonstration"""
    parser = argparse.ArgumentParser(description="IncidentIQ Analyst Agent")
    parser.add_argument("--incident", "-i", help="Incident ID to analyze", default="INC-042")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")
    args = parser.parse_args()
    
    console = Console()
    
    # Header
    console.print(Panel.fit(
        "🔬 [bold blue]IncidentIQ - Analyst Agent[/bold blue]",
        subtitle="Root Cause Analysis & Workflow Recommendation"
    ))
    
    try:
        # Initialize agent
        agent = AnalystAgent(verbose=not args.quiet)
        
        # Analyze incident
        console.print(f"\n🎯 Analyzing incident: {args.incident}")
        analysis = agent.analyze_incident(args.incident)
        
        if analysis:
            # Display results
            console.print("\n📋 [bold green]Analysis Results:[/bold green]")
            
            # Create results table
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="white")
            
            table.add_row("Root Cause", analysis.get("root_cause", "Unknown"))
            table.add_row("Recommended Workflow", analysis.get("recommended_workflow", "Unknown"))
            table.add_row("Confidence", f"{analysis.get('confidence', 0):.2%}")
            table.add_row("Similar Incidents", ", ".join(analysis.get("similar_incidents", [])))
            
            console.print(table)
            
            # Show reasoning
            console.print(f"\n💭 [bold yellow]Reasoning:[/bold yellow]")
            console.print(analysis.get("reasoning", "No reasoning provided"))
            
            # Show full JSON if verbose
            if not args.quiet:
                console.print(f"\n📄 [bold cyan]Full Analysis (JSON):[/bold cyan]")
                console.print(JSON(json.dumps(analysis, indent=2)))
        
        # Show stats
        stats = agent.get_stats()
        console.print(f"\n📊 [bold blue]Agent Stats:[/bold blue]")
        console.print(f"  • Analyses: {stats['analyses_performed']}")
        console.print(f"  • Success Rate: {stats['success_rate']:.1%}")
        
        if analysis:
            console.print("\n✅ [bold green]Analysis completed successfully![/bold green]")
            return 0
        else:
            console.print("\n❌ [bold red]Analysis failed![/bold red]")
            return 1
            
    except Exception as e:
        console.print(f"\n💥 [bold red]Fatal error: {e}[/bold red]")
        return 1


if __name__ == "__main__":
    exit(main())