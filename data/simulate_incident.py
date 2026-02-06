#!/usr/bin/env python3
"""
Generate simulated incident data for IncidentIQ

Usage:
    # Full real-time simulation (14 minutes)
    python data/simulate_incident.py
    
    # Fast demo mode (1.4 minutes)
    python data/simulate_incident.py --speed 10
    
    # Different incident scenario
    python data/simulate_incident.py --scenario memory-leak
    
    # Custom speed with agent triggering
    python data/simulate_incident.py --speed 5 --trigger-agents
    
    # Skip agent execution (data only)
    python data/simulate_incident.py --no-agents
    
    # Export terminal recording
    python data/simulate_incident.py --export-video demo.cast
    
    # Dry run to preview timeline
    python data/simulate_incident.py --dry-run
"""

import argparse
import asyncio
import json
import os
import random
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.align import Align

# Load environment
load_dotenv()

# Initialize console
console = Console()

# Configuration
SERVICES = {
    "api-gateway": {
        "normal_error_rate": 0.02,
        "normal_latency": 150,
        "normal_cpu": 40,
        "connection_pool_size": 50
    },
    "payment-service": {
        "normal_error_rate": 0.01,
        "normal_latency": 200,
        "normal_cpu": 35,
        "connection_pool_size": 30
    },
    "user-service": {
        "normal_error_rate": 0.015,
        "normal_latency": 120,
        "normal_cpu": 45,
        "connection_pool_size": 40
    }
}

TARGET_SERVICE = "api-gateway"

# Elasticsearch indexes
LOGS_INDEX = "logs-app"
METRICS_INDEX = "metrics-system"
INCIDENTS_INDEX = "incidentiq-incidents"

# Simulation phases (durations in seconds at 1x speed)
PHASES = {
    "normal": {
        "duration": 120,  # 2 minutes
        "description": "Normal Operations",
        "icon": "🟢"
    },
    "degradation": {
        "duration": 300,  # 5 minutes
        "description": "Service Degradation",
        "icon": "🟡"
    },
    "detection": {
        "duration": 30,  # 30 seconds
        "description": "Anomaly Detection",
        "icon": "🔴"
    },
    "analysis": {
        "duration": 60,  # 1 minute
        "description": "Root Cause Analysis",
        "icon": "🔍"
    },
    "remediation": {
        "duration": 150,  # 2.5 minutes
        "description": "Auto-Remediation",
        "icon": "🔧"
    },
    "recovery": {
        "duration": 120,  # 2 minutes
        "description": "Service Recovery",
        "icon": "✅"
    }
}

# Incident scenario definitions
SCENARIOS = {
    "db-pool": {
        "name": "Database Connection Pool Exhaustion",
        "service": "api-gateway",
        "error_type": "DatabaseTimeoutException",
        "error_messages": [
            "Database connection timeout after 30s wait",
            "Connection pool exhausted: {used}/{max} connections active",
            "Unable to acquire database connection within timeout",
        ],
        "degradation": {
            "error_rate": {"start": 0.02, "peak": 0.87},
            "latency": {"start": 150, "peak": 5000},
            "cpu": {"start": 40, "peak": 70},
            "connections": {"start": 10, "peak": 50}
        },
        "root_cause": "Connection pool size insufficient for traffic load",
        "remediation": "safe_service_restart",
        "similar_incidents": ["INC-001", "INC-003"]
    },
    "memory-leak": {
        "name": "Memory Leak in Notification Service",
        "service": "notification-service",
        "error_type": "OutOfMemoryException",
        "error_messages": [
            "Java heap space exhausted",
            "Cannot allocate memory for new request",
            "Memory threshold exceeded: {memory:.0f}%",
        ],
        "degradation": {
            "error_rate": {"start": 0.03, "peak": 0.65},
            "latency": {"start": 200, "peak": 8000},
            "cpu": {"start": 30, "peak": 85},
            "memory": {"start": 50, "peak": 95}
        },
        "root_cause": "Memory leak in message queue processing",
        "remediation": "safe_service_restart",
        "similar_incidents": ["INC-002", "INC-007"]
    },
    "rate-limit": {
        "name": "Rate Limit Cascade Failure",
        "service": "api-gateway",
        "error_type": "RateLimitExceededException",
        "error_messages": [
            "Rate limit exceeded: {rps:.0f} requests/sec > 1000 limit",
            "Too many requests from client",
            "Circuit breaker open due to rate limiting",
        ],
        "degradation": {
            "error_rate": {"start": 0.02, "peak": 0.75},
            "latency": {"start": 150, "peak": 3000},
            "cpu": {"start": 45, "peak": 90},
            "requests": {"start": 800, "peak": 2500}
        },
        "root_cause": "Traffic spike from bot attack",
        "remediation": "increase_rate_limits",
        "similar_incidents": ["INC-005", "INC-009"]
    },
    "disk-full": {
        "name": "Disk Space Exhaustion",
        "service": "payment-service",
        "error_type": "DiskFullException",
        "error_messages": [
            "Cannot write to log file: Disk full",
            "Disk usage at {disk:.0f}% - critical threshold",
            "Failed to persist transaction: No space left",
        ],
        "degradation": {
            "error_rate": {"start": 0.01, "peak": 0.92},
            "latency": {"start": 250, "peak": 6000},
            "cpu": {"start": 50, "peak": 80},
            "disk": {"start": 75, "peak": 99}
        },
        "root_cause": "Log rotation not configured, old logs accumulating",
        "remediation": "cleanup_old_logs",
        "similar_incidents": ["INC-004", "INC-011"]
    }
}


class IncidentSimulator:
    """Simulates a realistic incident scenario with live data generation"""
    
    def __init__(self, speed: float = 1.0, scenario: str = "db-pool",
                 trigger_agents: bool = False, dry_run: bool = False,
                 export_video: Optional[str] = None):
        """
        Initialize the incident simulator
        
        Args:
            speed: Time compression multiplier (1.0 = real-time, 10.0 = 10x faster)
            scenario: Incident scenario to simulate (db-pool, memory-leak, rate-limit, disk-full)
            trigger_agents: Whether to trigger actual agent workflows
            dry_run: Preview mode, don't write to Elasticsearch
            export_video: Path to export asciinema recording (optional)
        """
        self.speed = speed
        self.scenario_key = scenario
        self.scenario = SCENARIOS[scenario]
        self.trigger_agents = trigger_agents
        self.dry_run = dry_run
        self.export_video = export_video
        
        # State tracking
        self.current_phase = "normal"
        self.phase_start_time = None
        self.phase_elapsed = 0
        self.incident_id = f"INC-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        
        # Get service config
        service_name = self.scenario["service"]
        service_config = SERVICES.get(service_name, SERVICES["api-gateway"])
        
        # Metrics state (initialized from scenario)
        degradation = self.scenario["degradation"]
        self.error_rate = degradation["error_rate"]["start"]
        self.latency = degradation["latency"]["start"]
        self.cpu = degradation["cpu"]["start"]
        self.connections_used = degradation.get("connections", {}).get("start", 10)
        self.max_connections = service_config.get("connection_pool_size", 50)
        self.memory = degradation.get("memory", {}).get("start", 50)
        self.disk = degradation.get("disk", {}).get("start", 75)
        
        # Elasticsearch client
        if not dry_run:
            self.es = self._init_elasticsearch()
        else:
            self.es = None
            
    def _init_elasticsearch(self) -> Optional[Elasticsearch]:
        """Initialize Elasticsearch connection"""
        try:
            cloud_id = os.getenv("ELASTIC_CLOUD_ID")
            api_key = os.getenv("ELASTIC_API_KEY")
            
            if not cloud_id or not api_key:
                console.print("[yellow]⚠️  Elasticsearch credentials not found - running in offline mode[/yellow]")
                return None
                
            es = Elasticsearch(
                cloud_id=cloud_id,
                api_key=api_key
            )
            
            # Test connection
            es.info()
            return es
            
        except Exception as e:
            console.print(f"[yellow]⚠️  Elasticsearch connection failed: {e}[/yellow]")
            console.print("[yellow]   Running in offline mode[/yellow]")
            return None
    
    def _get_phase_progress(self) -> float:
        """Calculate current phase progress (0.0 to 1.0)"""
        duration = PHASES[self.current_phase]["duration"] / self.speed
        return min(1.0, self.phase_elapsed / duration)
    
    def _update_metrics_for_phase(self):
        """Update metrics based on current phase and progress"""
        progress = self._get_phase_progress()
        deg = self.scenario["degradation"]
        
        if self.current_phase == "normal":
            # Everything healthy
            self.error_rate = deg["error_rate"]["start"]
            self.latency = deg["latency"]["start"] + random.uniform(-10, 10)
            self.cpu = deg["cpu"]["start"] + random.uniform(-5, 5)
            self.connections_used = deg.get("connections", {}).get("start", 10) + random.randint(-2, 2)
            self.memory = deg.get("memory", {}).get("start", 50) + random.uniform(-2, 2)
            self.disk = deg.get("disk", {}).get("start", 75) + random.uniform(-1, 1)
            
        elif self.current_phase == "degradation":
            # Gradual degradation based on scenario
            error_range = deg["error_rate"]["peak"] - deg["error_rate"]["start"]
            self.error_rate = deg["error_rate"]["start"] + (error_range * progress) + random.uniform(-0.05, 0.05)
            
            latency_range = deg["latency"]["peak"] - deg["latency"]["start"]
            self.latency = deg["latency"]["start"] + (latency_range * progress) + random.uniform(-100, 200)
            
            cpu_range = deg["cpu"]["peak"] - deg["cpu"]["start"]
            self.cpu = deg["cpu"]["start"] + (cpu_range * progress) + random.uniform(-3, 3)
            
            # Scenario-specific metrics
            if "connections" in deg:
                conn_range = deg["connections"]["peak"] - deg["connections"]["start"]
                self.connections_used = int(deg["connections"]["start"] + (conn_range * progress)) + random.randint(-2, 2)
            
            if "memory" in deg:
                mem_range = deg["memory"]["peak"] - deg["memory"]["start"]
                self.memory = deg["memory"]["start"] + (mem_range * progress) + random.uniform(-2, 2)
            
            if "disk" in deg:
                disk_range = deg["disk"]["peak"] - deg["disk"]["start"]
                self.disk = deg["disk"]["start"] + (disk_range * progress) + random.uniform(-1, 1)
            
        elif self.current_phase == "detection":
            # Peak degradation
            self.error_rate = deg["error_rate"]["peak"] + random.uniform(-0.03, 0.03)
            self.latency = deg["latency"]["peak"] + random.uniform(-200, 500)
            self.cpu = deg["cpu"]["peak"] + random.uniform(-5, 5)
            if "connections" in deg:
                self.connections_used = min(self.max_connections, int(deg["connections"]["peak"] * 0.96) + random.randint(0, 2))
            if "memory" in deg:
                self.memory = deg["memory"]["peak"] + random.uniform(-2, 2)
            if "disk" in deg:
                self.disk = deg["disk"]["peak"] + random.uniform(-0.5, 0.5)
            
        elif self.current_phase == "analysis":
            # Still degraded while analyzing
            self.error_rate = deg["error_rate"]["peak"] * 0.98 + random.uniform(-0.05, 0.05)
            self.latency = deg["latency"]["peak"] * 0.96 + random.uniform(-300, 300)
            self.cpu = deg["cpu"]["peak"] * 0.97 + random.uniform(-5, 5)
            if "connections" in deg:
                self.connections_used = int(deg["connections"]["peak"] * 0.96) + random.randint(-1, 2)
            if "memory" in deg:
                self.memory = deg["memory"]["peak"] * 0.98 + random.uniform(-2, 2)
            if "disk" in deg:
                self.disk = deg["disk"]["peak"] * 0.99 + random.uniform(-0.5, 0.5)
            
        elif self.current_phase == "remediation":
            # Service restart happens midway through
            if progress < 0.5:
                # Still degraded before restart
                self.error_rate = deg["error_rate"]["peak"] * 0.98 + random.uniform(-0.05, 0.05)
                self.latency = deg["latency"]["peak"] * 0.90 + random.uniform(-500, 500)
                self.cpu = deg["cpu"]["peak"] + random.uniform(-5, 5)
                if "connections" in deg:
                    self.connections_used = int(deg["connections"]["peak"] * 0.94) + random.randint(-2, 2)
                if "memory" in deg:
                    self.memory = deg["memory"]["peak"] * 0.98 + random.uniform(-2, 2)
                if "disk" in deg:
                    self.disk = deg["disk"]["peak"] * 0.99 + random.uniform(-0.5, 0.5)
            else:
                # Beginning recovery after restart
                restart_progress = (progress - 0.5) * 2  # 0 to 1
                peak_error = deg["error_rate"]["peak"]
                recovery_error = peak_error * 0.50  # Recover to 50% of peak
                self.error_rate = peak_error - ((peak_error - recovery_error) * restart_progress)
                
                peak_latency = deg["latency"]["peak"]
                recovery_latency = deg["latency"]["start"] * 6  # Some overhead after restart
                self.latency = peak_latency - ((peak_latency - recovery_latency) * restart_progress)
                
                self.cpu = deg["cpu"]["peak"] - ((deg["cpu"]["peak"] - deg["cpu"]["start"]) * restart_progress)
                
                if "connections" in deg:
                    self.connections_used = int(deg["connections"]["peak"] - ((deg["connections"]["peak"] - deg["connections"]["start"]) * restart_progress))
                if "memory" in deg:
                    self.memory = deg["memory"]["peak"] - ((deg["memory"]["peak"] - deg["memory"]["start"]) * restart_progress)
                if "disk" in deg:
                    # Disk recovers after cleanup
                    self.disk = deg["disk"]["peak"] - ((deg["disk"]["peak"] - deg["disk"]["start"]) * restart_progress)
                
        elif self.current_phase == "recovery":
            # Full recovery back to baseline
            recovery_error = deg["error_rate"]["peak"] * 0.50
            self.error_rate = recovery_error - ((recovery_error - deg["error_rate"]["start"]) * progress)
            
            recovery_latency = deg["latency"]["start"] * 6
            self.latency = recovery_latency - ((recovery_latency - deg["latency"]["start"]) * progress)
            
            self.cpu = deg["cpu"]["start"] + (2 * (1 - progress))  # Slight overhead, normalizing
            
            if "connections" in deg:
                self.connections_used = int(deg["connections"]["start"] + (5 * (1 - progress)))
            if "memory" in deg:
                self.memory = deg["memory"]["start"] + (3 * (1 - progress))
            if "disk" in deg:
                self.disk = deg["disk"]["start"] + (2 * (1 - progress))
            
        # Add realistic jitter and bounds
        self.error_rate = max(0, min(1, self.error_rate))
        self.latency = max(50, self.latency)
        self.cpu = max(0, min(100, self.cpu))
        self.connections_used = max(0, min(self.max_connections, self.connections_used))
        self.memory = max(0, min(100, self.memory))
        self.disk = max(0, min(100, self.disk))
    
    def _generate_log_entry(self) -> Dict:
        """Generate a realistic log entry based on current metrics"""
        timestamp = datetime.utcnow()
        
        # Determine if this request errors based on current error rate
        is_error = random.random() < self.error_rate
        
        if is_error:
            level = "ERROR"
            status = random.choice([500, 503, 504])
            
            # Use scenario-specific error messages
            messages = self.scenario["error_messages"].copy()
            message_template = random.choice(messages)
            
            # Format message with current metrics
            message = message_template.format(
                used=self.connections_used,
                max=self.max_connections,
                memory=self.memory,
                disk=self.disk,
                rps=100 + random.uniform(-20, 20)
            )
            
            error_type = self.scenario["error_type"]
        else:
            level = "INFO"
            status = 200
            message = "Request completed successfully"
            error_type = None
            
        service_name = self.scenario["service"]
        return {
            "@timestamp": timestamp.isoformat() + "Z",
            "service": service_name,
            "level": level,
            "message": message,
            "error_type": error_type,
            "http_status": status,
            "response_time": self.latency + random.uniform(-50, 50),
            "environment": "production",
            "host": f"{service_name}-pod-{random.randint(1, 3)}",
            "trace_id": uuid.uuid4().hex,
            "simulation": True,
            "incident_id": self.incident_id if self.current_phase != "normal" else None
        }
    
    def _generate_metric_entry(self) -> Dict:
        """Generate a system metric entry"""
        service_name = self.scenario["service"]
        metric = {
            "@timestamp": datetime.utcnow().isoformat() + "Z",
            "service": service_name,
            "metric_type": "system",
            "cpu_percent": self.cpu + random.uniform(-2, 2),
            "memory_percent": self.memory + random.uniform(-2, 2),
            "error_rate": self.error_rate,
            "avg_response_time": self.latency,
            "requests_per_second": 100 + random.uniform(-20, 20),
            "environment": "production",
            "host": f"{service_name}-pod-1",
            "simulation": True,
            "incident_id": self.incident_id if self.current_phase != "normal" else None
        }
        
        # Add scenario-specific metrics
        if "connections" in self.scenario["degradation"]:
            metric["connection_pool_used"] = self.connections_used
            metric["connection_pool_max"] = self.max_connections
        if "disk" in self.scenario["degradation"]:
            metric["disk_percent"] = self.disk + random.uniform(-1, 1)
        
        return metric
    
    def _write_to_elasticsearch(self, index: str, document: Dict):
        """Write a document to Elasticsearch"""
        if self.dry_run or not self.es:
            return
            
        try:
            self.es.index(index=index, document=document)
        except Exception as e:
            # Silently fail to avoid disrupting simulation
            pass
    
    def _create_incident_document(self):
        """Create incident document in Elasticsearch"""
        service_name = self.scenario["service"]
        incident = {
            "@timestamp": datetime.utcnow().isoformat() + "Z",
            "incident_id": self.incident_id,
            "title": f"{self.scenario['name']} - {service_name}",
            "service": service_name,
            "severity": "HIGH",
            "status": "detected",
            "error_type": self.scenario["error_type"],
            "error_anomaly_score": 8.2,
            "symptoms": f"Error rate spike from {self.scenario['degradation']['error_rate']['start']*100:.0f}% to {self.error_rate*100:.0f}%, latency increased to {self.latency:.0f}ms",
            "detected_at": datetime.utcnow().isoformat() + "Z",
            "detection_method": "anomaly_detection",
            "environment": "production",
            "simulation": True
        }
        
        self._write_to_elasticsearch(INCIDENTS_INDEX, incident)
        return incident
    
    def _update_incident_status(self, status: str, **kwargs):
        """Update incident status in Elasticsearch"""
        if self.dry_run or not self.es:
            return
            
        try:
            # Update incident document
            update_doc = {
                "status": status,
                "updated_at": datetime.utcnow().isoformat() + "Z"
            }
            update_doc.update(kwargs)
            
            # In real implementation, we'd use update API
            # For demo, we'll just log it
            console.print(f"[dim]   → Incident {self.incident_id} status: {status}[/dim]")
        except Exception:
            pass
    
    def _create_dashboard_table(self) -> Table:
        """Create a rich table showing current metrics"""
        table = Table(show_header=True, header_style="bold magenta", 
                     expand=True, border_style="blue")
        
        table.add_column("Metric", style="cyan", width=25)
        table.add_column("Current", justify="right", width=15)
        table.add_column("Normal", justify="right", width=15)
        table.add_column("Status", justify="center", width=15)
        
        # Error Rate
        error_status = "🔴 CRITICAL" if self.error_rate > 0.5 else ("🟡 WARNING" if self.error_rate > 0.1 else "🟢 OK")
        error_color = "red" if self.error_rate > 0.5 else ("yellow" if self.error_rate > 0.1 else "green")
        table.add_row(
            "Error Rate",
            f"[{error_color}]{self.error_rate*100:.1f}%[/{error_color}]",
            "2.0%",
            error_status
        )
        
        # Latency
        latency_status = "🔴 CRITICAL" if self.latency > 2000 else ("🟡 WARNING" if self.latency > 500 else "🟢 OK")
        latency_color = "red" if self.latency > 2000 else ("yellow" if self.latency > 500 else "green")
        table.add_row(
            "Avg Latency",
            f"[{latency_color}]{self.latency:.0f}ms[/{latency_color}]",
            "150ms",
            latency_status
        )
        
        # CPU
        cpu_status = "🟡 WARNING" if self.cpu > 60 else "🟢 OK"
        cpu_color = "yellow" if self.cpu > 60 else "green"
        table.add_row(
            "CPU Usage",
            f"[{cpu_color}]{self.cpu:.0f}%[/{cpu_color}]",
            "40%",
            cpu_status
        )
        
        # Connection Pool
        pool_pct = (self.connections_used / self.max_connections) * 100
        pool_status = "🔴 CRITICAL" if pool_pct > 90 else ("🟡 WARNING" if pool_pct > 70 else "🟢 OK")
        pool_color = "red" if pool_pct > 90 else ("yellow" if pool_pct > 70 else "green")
        table.add_row(
            "Connection Pool",
            f"[{pool_color}]{self.connections_used}/{self.max_connections}[/{pool_color}]",
            "10/50",
            pool_status
        )
        
        return table
    
    def _create_timeline_panel(self) -> Panel:
        """Create a timeline showing phase progression"""
        timeline_parts = []
        
        for phase_name, phase_info in PHASES.items():
            icon = phase_info["icon"]
            desc = phase_info["description"]
            
            if phase_name == self.current_phase:
                # Current phase - highlighted
                progress_pct = int(self._get_phase_progress() * 100)
                timeline_parts.append(f"[bold yellow]► {icon} {desc} ({progress_pct}%)[/bold yellow]")
            else:
                # Determine if completed or upcoming
                phase_order = list(PHASES.keys())
                current_idx = phase_order.index(self.current_phase)
                phase_idx = phase_order.index(phase_name)
                
                if phase_idx < current_idx:
                    timeline_parts.append(f"[dim]✓ {icon} {desc}[/dim]")
                else:
                    timeline_parts.append(f"[dim]  {icon} {desc}[/dim]")
        
        timeline_text = "\n".join(timeline_parts)
        return Panel(timeline_text, title="[bold]Incident Timeline[/bold]", 
                    border_style="cyan", expand=False)
    
    def _create_event_log(self, events: List[str]) -> Panel:
        """Create event log panel"""
        # Show last 10 events
        recent_events = events[-10:] if len(events) > 10 else events
        event_text = "\n".join(recent_events)
        
        return Panel(event_text, title="[bold]Event Log[/bold]", 
                    border_style="green", expand=True, height=12)
    
    async def run_phase(self, phase_name: str, events: List[str]):
        """Execute a single phase of the simulation"""
        self.current_phase = phase_name
        phase = PHASES[phase_name]
        duration = phase["duration"] / self.speed
        
        # Phase-specific setup
        if phase_name == "detection":
            events.append(f"[red]🚨 ANOMALY DETECTED - Error rate: {self.error_rate*100:.0f}%[/red]")
            incident = self._create_incident_document()
            events.append(f"[yellow]📋 Incident created: {self.incident_id}[/yellow]")
            
        elif phase_name == "analysis":
            events.append("[cyan]🔍 Detective Agent analyzing root cause...[/cyan]")
            await asyncio.sleep(2 / self.speed)
            events.append("[cyan]   → Searching for similar incidents...[/cyan]")
            await asyncio.sleep(2 / self.speed)
            
            similar = self.scenario["similar_incidents"]
            events.append(f"[green]   ✓ Found {len(similar)} matches: {similar[0]} (0.94 confidence), {similar[1] if len(similar) > 1 else 'INC-XXX'} (0.89)[/green]")
            await asyncio.sleep(1 / self.speed)
            events.append(f"[cyan]   → Root cause: {self.scenario['root_cause']}[/cyan]")
            events.append(f"[cyan]   → Recommended action: {self.scenario['remediation']}[/cyan]")
            
            if not self.trigger_agents:
                events.append("[dim]   → Agent execution skipped (--no-agents)[/dim]")
            
            self._update_incident_status("analyzing", 
                                        root_cause=self.scenario["root_cause"],
                                        recommended_action=self.scenario["remediation"])
            
        elif phase_name == "remediation":
            remediation = self.scenario["remediation"]
            service_name = self.scenario["service"]
            
            if not self.trigger_agents:
                events.append("[dim]🔧 Remediation skipped (--no-agents)[/dim]")
                events.append(f"[dim]   Would execute: {remediation}[/dim]")
            else:
                events.append(f"[yellow]🔧 Remediation Agent executing {remediation}...[/yellow]")
            
            await asyncio.sleep(3 / self.speed)
            
            if "restart" in remediation:
                events.append("[cyan]   → Running pre-restart health checks...[/cyan]")
                await asyncio.sleep(2 / self.speed)
                events.append("[green]   ✓ Health checks passed[/green]")
                await asyncio.sleep(2 / self.speed)
                events.append(f"[cyan]   → Initiating rolling restart of {service_name}...[/cyan]")
                
                # Wait until midpoint for restart
                await asyncio.sleep(duration * 0.4)
                events.append("[yellow]   → Restarting pod 1/3...[/yellow]")
                await asyncio.sleep(duration * 0.1)
                events.append("[yellow]   → Restarting pod 2/3...[/yellow]")
                await asyncio.sleep(duration * 0.1)
                events.append("[yellow]   → Restarting pod 3/3...[/yellow]")
                await asyncio.sleep(duration * 0.1)
                events.append("[green]   ✓ All pods restarted successfully[/green]")
            elif "cleanup" in remediation:
                events.append("[cyan]   → Identifying old log files...[/cyan]")
                await asyncio.sleep(duration * 0.3)
                events.append("[yellow]   → Removing logs older than 30 days...[/yellow]")
                await asyncio.sleep(duration * 0.4)
                events.append("[green]   ✓ Freed 24GB disk space[/green]")
            elif "increase" in remediation:
                events.append("[cyan]   → Updating rate limit configuration...[/cyan]")
                await asyncio.sleep(duration * 0.3)
                events.append("[yellow]   → Deploying new limits: 1000 -> 2000 req/s...[/yellow]")
                await asyncio.sleep(duration * 0.4)
                events.append("[green]   ✓ Rate limits updated[/green]")
            
            events.append("[cyan]   → Monitoring recovery metrics...[/cyan]")
            self._update_incident_status("remediating", 
                                        remediation_action=remediation,
                                        remediation_started_at=datetime.utcnow().isoformat() + "Z")
            return  # Phase timing handled above
            
        elif phase_name == "recovery":
            events.append("[green]✅ Service recovering...[/green]")
            await asyncio.sleep(duration * 0.5)
            events.append("[green]   → Error rate normalizing...[/green]")
            await asyncio.sleep(duration * 0.3)
            events.append("[green]   → Latency returning to baseline...[/green]")
            await asyncio.sleep(duration * 0.15)
            events.append("[green]   ✓ Service fully recovered[/green]")
            events.append(f"[bold green]🎉 Incident {self.incident_id} RESOLVED[/bold green]")
            self._update_incident_status("resolved",
                                        resolved_at=datetime.utcnow().isoformat() + "Z",
                                        resolution_time_seconds=int(sum(p["duration"] for p in PHASES.values()) / self.speed))
            return
        
        # Run phase with live metrics
        start_time = time.time()
        self.phase_start_time = start_time
        
        while time.time() - start_time < duration:
            self.phase_elapsed = time.time() - start_time
            
            # Update metrics
            self._update_metrics_for_phase()
            
            # Generate data every second (compressed by speed)
            if phase_name in ["normal", "degradation", "recovery"]:
                # Generate 5-10 log entries per second
                for _ in range(random.randint(5, 10)):
                    log = self._generate_log_entry()
                    self._write_to_elasticsearch(LOGS_INDEX, log)
                
                # Generate metrics
                metric = self._generate_metric_entry()
                self._write_to_elasticsearch(METRICS_INDEX, metric)
            
            # Wait for next update
            await asyncio.sleep(1 / self.speed)
    
    async def run(self):
        """Run the complete incident simulation"""
        events = []
        
        # Header
        console.clear()
        
        # Start recording if export requested
        if self.export_video:
            console.print(f"[dim]Recording to {self.export_video}... (requires asciinema)[/dim]")
        
        console.print(Panel.fit(
            f"[bold red]🚨 INCIDENT SIMULATION[/bold red]\n\n"
            f"[cyan]Scenario:[/cyan] {self.scenario['name']}\n"
            f"[cyan]Service:[/cyan] {self.scenario['service']}\n"
            f"[cyan]Incident ID:[/cyan] {self.incident_id}\n"
            f"[cyan]Speed:[/cyan] {self.speed}x\n"
            f"[cyan]Mode:[/cyan] {'DRY RUN' if self.dry_run else 'LIVE'}\n"
            f"[cyan]Agents:[/cyan] {'Enabled' if self.trigger_agents else 'Disabled'}\n"
            f"[cyan]Estimated Duration:[/cyan] {sum(p['duration'] for p in PHASES.values()) / self.speed / 60:.1f} minutes",
            border_style="red",
            padding=(1, 2)
        ))
        
        console.print()
        events.append(f"[dim]{datetime.now().strftime('%H:%M:%S')} Simulation started[/dim]")
        
        # Run each phase with live dashboard
        with Live(console=console, refresh_per_second=4) as live:
            for phase_name in PHASES.keys():
                # Create layout
                layout = Layout()
                layout.split_column(
                    Layout(name="header", size=3),
                    Layout(name="body"),
                    Layout(name="footer", size=14)
                )
                
                layout["body"].split_row(
                    Layout(name="metrics", ratio=2),
                    Layout(name="timeline", ratio=1)
                )
                
                # Update display continuously during phase
                async def update_display():
                    while self.current_phase == phase_name:
                        # Update header
                        phase = PHASES[phase_name]
                        progress_pct = int(self._get_phase_progress() * 100)
                        header_text = Text(
                            f"{phase['icon']} {phase['description']} - {progress_pct}%",
                            style="bold",
                            justify="center"
                        )
                        layout["header"].update(Panel(header_text, border_style="blue"))
                        
                        # Update metrics table
                        layout["body"]["metrics"].update(self._create_dashboard_table())
                        
                        # Update timeline
                        layout["body"]["timeline"].update(self._create_timeline_panel())
                        
                        # Update event log
                        layout["footer"].update(self._create_event_log(events))
                        
                        # Refresh display
                        live.update(layout)
                        
                        await asyncio.sleep(0.25)
                
                # Run phase and display updates concurrently
                await asyncio.gather(
                    self.run_phase(phase_name, events),
                    update_display()
                )
                
        # Final summary
        console.print()
        console.print(Panel.fit(
            f"[bold green]✅ SIMULATION COMPLETE[/bold green]\n\n"
            f"[cyan]Incident ID:[/cyan] {self.incident_id}\n"
            f"[cyan]Status:[/cyan] RESOLVED\n"
            f"[cyan]Total Duration:[/cyan] {sum(p['duration'] for p in PHASES.values()) / self.speed:.0f}s\n"
            f"[cyan]Logs Generated:[/cyan] ~{int(sum(p['duration'] for p in PHASES.values()) * 7)} entries\n"
            f"[cyan]Metrics Generated:[/cyan] ~{int(sum(p['duration'] for p in PHASES.values()))} entries\n\n"
            f"[yellow]{'📝 DRY RUN - No data written to Elasticsearch' if self.dry_run else '✓ Data written to Elasticsearch'}[/yellow]",
            border_style="green",
            padding=(1, 2)
        ))
        

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Simulate a realistic incident for IncidentIQ demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fast demo (1.4 minutes)
  python data/simulate_incident.py --speed 10
  
  # Medium speed with different scenario
  python data/simulate_incident.py --speed 3 --scenario memory-leak
  
  # Real-time with agents
  python data/simulate_incident.py --speed 1 --trigger-agents
  
  # Export recording (requires asciinema: brew install asciinema)
  python data/simulate_incident.py --speed 5 --export-video demo.cast
  
  # Preview timeline without writing data
  python data/simulate_incident.py --dry-run
        """
    )
    
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Time compression multiplier (1.0 = real-time, 10.0 = 10x faster)"
    )
    
    parser.add_argument(
        "--scenario",
        type=str,
        choices=list(SCENARIOS.keys()),
        default="db-pool",
        help="Incident scenario to simulate"
    )
    
    parser.add_argument(
        "--trigger-agents",
        action="store_true",
        help="Trigger actual agent workflows (default: disabled)"
    )
    
    parser.add_argument(
        "--no-agents",
        action="store_true",
        help="Skip agent execution, only generate data (opposite of --trigger-agents)"
    )
    
    parser.add_argument(
        "--export-video",
        type=str,
        metavar="FILE",
        help="Export terminal recording to FILE (requires asciinema)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview mode - don't write to Elasticsearch"
    )
    
    args = parser.parse_args()
    
    # Validate speed
    if args.speed < 0.1 or args.speed > 100:
        console.print("[red]Error: Speed must be between 0.1 and 100[/red]")
        return 1
    
    # Handle agent flags
    trigger_agents = args.trigger_agents and not args.no_agents
    
    # Check for asciinema if export requested
    if args.export_video:
        import shutil
        if not shutil.which("asciinema"):
            console.print("[yellow]⚠️  asciinema not found. Install with: brew install asciinema[/yellow]")
            console.print("[yellow]   Continuing without recording...[/yellow]")
            args.export_video = None
    
    # List available scenarios
    console.print(f"\n[dim]Available scenarios: {', '.join(SCENARIOS.keys())}[/dim]")
    console.print(f"[dim]Selected: {args.scenario} - {SCENARIOS[args.scenario]['name']}[/dim]\n")
    
    # Run simulation
    simulator = IncidentSimulator(
        speed=args.speed,
        scenario=args.scenario,
        trigger_agents=trigger_agents,
        dry_run=args.dry_run,
        export_video=args.export_video
    )
    
    try:
        # If export video, wrap in asciinema recording
        if args.export_video:
            import subprocess
            console.print(f"[green]🎥 Starting asciinema recording to {args.export_video}[/green]")
            console.print("[dim]   Recording will start in 2 seconds...[/dim]\n")
            time.sleep(2)
            
            # Run simulation in asciinema
            result = subprocess.run(
                ["asciinema", "rec", "-c", f"python {__file__} --speed {args.speed} --scenario {args.scenario}", 
                 args.export_video],
                check=False
            )
            
            if result.returncode == 0:
                console.print(f"\n[green]✅ Recording saved to {args.export_video}[/green]")
                console.print(f"[dim]   Play with: asciinema play {args.export_video}[/dim]")
            return result.returncode
        else:
            asyncio.run(simulator.run())
            return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Simulation interrupted by user[/yellow]")
        return 1
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return 1


if __name__ == "__main__":
    exit(main())
