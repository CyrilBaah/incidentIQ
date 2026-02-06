#!/usr/bin/env python3
"""
Detective Agent - Monitors for incidents in real-time

Usage:
    python src/detective_agent.py                  # Run continuously
    python src/detective_agent.py --interval 30    # Check every 30 seconds
    python src/detective_agent.py --once           # Run once and exit
"""

import os
import sys
import time
import hashlib
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel

load_dotenv()
console = Console()


class DetectiveAgent:
    """Detective Agent - Detects anomalies and creates incidents"""
    
    def __init__(self, interval_seconds: int = 60, verbose: bool = True):
        """
        Initialize Detective Agent
        
        Args:
            interval_seconds: How often to check (default 60s)
            verbose: Print detailed output
        """
        self.interval = interval_seconds
        self.verbose = verbose
        self.running = False
        
        # Connect to Elasticsearch
        self.es = Elasticsearch(
            cloud_id=os.getenv("ELASTIC_CLOUD_ID"),
            api_key=os.getenv("ELASTIC_API_KEY")
        )
        
        # Track recent incidents (for deduplication)
        self.recent_incidents = {}  # {error_signature: incident_id}
        self.dedup_window = 300  # 5 minutes in seconds
        
        # Statistics
        self.checks_performed = 0
        self.incidents_created = 0
        self.last_check_time = None
        
        if self.verbose:
            console.print("[green]✅ Detective Agent initialized[/green]")
    
    def load_query(self) -> str:
        """Load the anomaly detection ES|QL query"""
        query_path = "tools/esql/detect_anomalies.esql"
        
        if not os.path.exists(query_path):
            raise FileNotFoundError(f"Query file not found: {query_path}")
        
        with open(query_path, 'r') as f:
            return f.read()
    
    def execute_detection_query(self) -> List[Dict[str, Any]]:
        """
        Execute anomaly detection query
        
        Returns:
            List of anomaly dictionaries
        """
        query = self.load_query()
        
        # Replace template variables
        query = query.replace("$time_window", "2m")
        query = query.replace("$anomaly_threshold", "3.0")
        
        try:
            result = self.es.esql.query(query=query)
            
            # Convert to list of dicts
            columns = [col['name'] for col in result.get('columns', [])]
            rows = result.get('values', [])
            
            anomalies = []
            for row in rows:
                anomaly = dict(zip(columns, row))
                anomalies.append(anomaly)
            
            return anomalies
            
        except Exception as e:
            console.print(f"[red]❌ Query execution failed: {e}[/red]")
            return []
    
    def generate_error_signature(self, service: str, error_type: str) -> str:
        """Generate unique error signature (hash)"""
        signature_str = f"{service}:{error_type}"
        return hashlib.md5(signature_str.encode()).hexdigest()[:16]
    
    def calculate_severity(self, max_anomaly_score: float) -> str:
        """Calculate incident severity based on anomaly score"""
        if max_anomaly_score >= 5.0:
            return "CRITICAL"
        elif max_anomaly_score >= 3.0:
            return "HIGH"
        elif max_anomaly_score >= 2.0:
            return "MEDIUM"
        else:
            return "LOW"
    
    def generate_incident_id(self) -> str:
        """Generate next incident ID"""
        # Query for latest incident
        try:
            result = self.es.search(
                index="incidents-*",
                body={
                    "size": 1,
                    "sort": [{"@timestamp": "desc"}],
                    "_source": ["incident_id"]
                }
            )
            
            if result['hits']['hits']:
                last_id = result['hits']['hits'][0]['_source'].get('incident_id', 'INC-000')
                # Extract number and increment
                num = int(last_id.split('-')[1]) + 1
            else:
                num = 1
            
            return f"INC-{num:03d}"
            
        except:
            # Fallback to timestamp-based ID
            return f"INC-{int(time.time()) % 1000:03d}"
    
    def create_incident(self, anomaly: Dict[str, Any]) -> Optional[str]:
        """
        Create incident document in Elasticsearch
        
        Returns:
            Incident ID if created, None if duplicate
        """
        service = anomaly.get('service', 'unknown')
        error_type = anomaly.get('error_type', 'UnknownError')
        max_anomaly_score = anomaly.get('max_anomaly_score', 0)
        
        # Generate error signature
        error_signature = self.generate_error_signature(service, error_type)
        
        # Check for recent duplicate
        if error_signature in self.recent_incidents:
            last_incident_time = self.recent_incidents[error_signature]['time']
            if (datetime.now() - last_incident_time).total_seconds() < self.dedup_window:
                if self.verbose:
                    console.print(f"  ⏩ Skipping duplicate: {service} - {error_type}")
                return None
        
        # Generate incident ID
        incident_id = self.generate_incident_id()
        
        # Calculate severity
        severity = self.calculate_severity(max_anomaly_score)
        
        # Create incident document
        incident = {
            "@timestamp": datetime.utcnow().isoformat(),
            "incident_id": incident_id,
            "status": "active",
            "severity": severity,
            "service": service,
            "environment": "production",
            "error_type": error_type,
            "error_signature": error_signature,
            "detected_at": datetime.utcnow().isoformat(),
            "detection_agent": "detective_agent",
            "anomaly_scores": {
                "error": anomaly.get('error_anomaly_score', 0),
                "latency": anomaly.get('latency_anomaly_score', 0),
                "cpu": anomaly.get('cpu_anomaly_score', 0),
                "max": max_anomaly_score
            },
            "current_metrics": {
                "error_rate": anomaly.get('current_error_rate', 0),
                "latency_p95": anomaly.get('current_latency_p95', 0),
                "cpu": anomaly.get('current_cpu', 0)
            },
            "baseline_metrics": {
                "error_mean": anomaly.get('baseline_error_mean', 0),
                "latency_mean": anomaly.get('baseline_latency_mean', 0),
                "cpu_mean": anomaly.get('baseline_cpu_mean', 0)
            },
            "auto_resolved": False,
            "tags": ["auto-detected", f"severity-{severity.lower()}"]
        }
        
        # Insert into Elasticsearch
        try:
            self.es.index(
                index="incidents-active",
                document=incident
            )
            
            # Track for deduplication
            self.recent_incidents[error_signature] = {
                'incident_id': incident_id,
                'time': datetime.now()
            }
            
            # Update statistics
            self.incidents_created += 1
            
            if self.verbose:
                console.print(
                    f"[bold red]🚨 INCIDENT CREATED:[/bold red] "
                    f"{incident_id} - {service} - {error_type} "
                    f"(severity: {severity}, score: {max_anomaly_score:.2f}σ)"
                )
            
            return incident_id
            
        except Exception as e:
            console.print(f"[red]❌ Failed to create incident: {e}[/red]")
            return None
    
    def check_for_anomalies(self):
        """Run one detection cycle"""
        self.checks_performed += 1
        self.last_check_time = datetime.now()
        
        if self.verbose:
            console.print(f"\n[cyan]🔍 Running anomaly detection check #{self.checks_performed}...[/cyan]")
        
        # Execute query
        anomalies = self.execute_detection_query()
        
        if not anomalies:
            if self.verbose:
                console.print("[green]  ✓ No anomalies detected - all systems healthy[/green]")
            return
        
        # Process each anomaly
        console.print(f"[yellow]  ⚠️  Detected {len(anomalies)} anomalies[/yellow]")
        
        for anomaly in anomalies:
            incident_id = self.create_incident(anomaly)
            if incident_id:
                # Could trigger Analyst Agent here in future
                pass
    
    def run_continuous(self):
        """Run continuously until stopped"""
        self.running = True
        
        console.print(Panel.fit(
            f"[bold]🕵️  Detective Agent Running[/bold]\n"
            f"Checking every {self.interval} seconds\n"
            f"Press Ctrl+C to stop",
            border_style="cyan"
        ))
        
        try:
            while self.running:
                self.check_for_anomalies()
                
                # Show status
                if self.verbose:
                    console.print(
                        f"[dim]Next check in {self.interval}s "
                        f"(Checks: {self.checks_performed}, Incidents: {self.incidents_created})[/dim]"
                    )
                
                # Wait for next interval
                time.sleep(self.interval)
                
        except KeyboardInterrupt:
            console.print("\n[yellow]⏹️  Stopping Detective Agent...[/yellow]")
            self.running = False
        
        # Final statistics
        console.print(Panel.fit(
            f"[bold]Detective Agent Statistics[/bold]\n"
            f"Checks performed: {self.checks_performed}\n"
            f"Incidents created: {self.incidents_created}\n"
            f"Runtime: {(datetime.now() - self.last_check_time).total_seconds() if self.last_check_time else 0:.0f}s",
            border_style="green"
        ))
    
    def run_once(self):
        """Run detection once and exit"""
        console.print("[cyan]🔍 Running single detection check...[/cyan]")
        self.check_for_anomalies()
        console.print("[green]✅ Check complete[/green]")


def main():
    parser = argparse.ArgumentParser(description="Detective Agent - Incident Detection")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    
    args = parser.parse_args()
    
    agent = DetectiveAgent(
        interval_seconds=args.interval,
        verbose=not args.quiet
    )
    
    if args.once:
        agent.run_once()
    else:
        agent.run_continuous()


if __name__ == "__main__":
    main()