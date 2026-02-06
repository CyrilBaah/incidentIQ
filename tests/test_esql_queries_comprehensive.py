#!/usr/bin/env python3
"""
Comprehensive ES|QL query testing and tuning

Usage:
    python tests/test_esql_queries_comprehensive.py
    python tests/test_esql_queries_comprehensive.py --verbose
    python tests/test_esql_queries_comprehensive.py --tune  # Auto-tune thresholds
"""

import argparse
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

load_dotenv()
console = Console()


class ESQLQueryTester:
    """Test and tune ES|QL queries"""
    
    def __init__(self, verbose: bool = False):
        self.es = self._setup_elasticsearch()
        self.results = {}
        self.verbose = verbose
        
        # Verify connection
        try:
            info = self.es.info()
            if self.verbose:
                console.print(f"[dim]Connected to Elasticsearch: {info['cluster_name']}[/dim]")
        except Exception as e:
            console.print(f"[red]❌ Failed to connect to Elasticsearch: {e}[/red]")
            raise
    
    def _setup_elasticsearch(self) -> Elasticsearch:
        """Setup Elasticsearch connection"""
        es_config = {}
        
        if os.getenv("ELASTIC_CLOUD_ID"):
            es_config["cloud_id"] = os.getenv("ELASTIC_CLOUD_ID")
            if os.getenv("ELASTIC_API_KEY"):
                es_config["api_key"] = os.getenv("ELASTIC_API_KEY")
            elif os.getenv("ELASTIC_PASSWORD"):
                es_config["basic_auth"] = ("elastic", os.getenv("ELASTIC_PASSWORD"))
        else:
            es_config["hosts"] = [os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")]
            if os.getenv("ELASTIC_PASSWORD"):
                es_config["basic_auth"] = ("elastic", os.getenv("ELASTIC_PASSWORD"))
        
        return Elasticsearch(**es_config)
    
    def load_query(self, filename: str) -> str:
        """Load ES|QL query from file"""
        path = f"tools/esql/{filename}"
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            console.print(f"[yellow]⚠️  Query file not found: {path}[/yellow]")
            raise
    
    def test_detect_anomalies(self) -> Dict[str, Any]:
        """Test anomaly detection query"""
        console.print("\n[bold cyan]━━━ Testing: detect_anomalies.esql ━━━[/bold cyan]")
        
        try:
            query = self.load_query("detect_anomalies.esql")
        except FileNotFoundError:
            return {
                "query": "detect_anomalies.esql",
                "status": "SKIP",
                "error": "Query file not found"
            }
        
        # Test 1: Current data (should be normal baseline)
        test_query = query.replace("$time_window", "2m").replace("$anomaly_threshold", "3.0")
        
        if self.verbose:
            console.print(f"[dim]Query parameters: time_window=2m, threshold=3.0σ[/dim]")
        
        try:
            result = self.es.esql.query(query=test_query)
            rows = result.get('values', [])
            columns = [col['name'] for col in result.get('columns', [])]
            
            console.print(f"  ✓ Query executed successfully")
            console.print(f"  ✓ Anomalies detected: {len(rows)}")
            
            # Determine status based on results
            if len(rows) == 0:
                console.print("  [green]✓ No anomalies in baseline (expected)[/green]")
                status = "PASS"
                suggestion = "Threshold of 3.0σ seems appropriate for baseline data"
            elif len(rows) < 5:
                console.print(f"  [yellow]⚠️  Few anomalies detected (acceptable for baseline)[/yellow]")
                status = "PASS"
                suggestion = "Monitor for false positives - consider increasing to 3.5σ if too noisy"
            else:
                console.print(f"  [red]❌ Too many anomalies ({len(rows)}) - likely false positives[/red]")
                status = "FAIL"
                suggestion = "Increase threshold to 3.5σ or 4.0σ to reduce false positives"
            
            # Show sample results if any
            if rows and len(rows) > 0:
                table = Table(title="Sample Anomalies", show_lines=True)
                # Add first 6 columns
                for col in columns[:min(6, len(columns))]:
                    table.add_column(col, overflow="fold")
                
                for row in rows[:min(3, len(rows))]:
                    table.add_row(*[str(val)[:30] for val in row[:min(6, len(columns))]])
                
                console.print(table)
            
            return {
                "query": "detect_anomalies.esql",
                "status": status,
                "anomalies_found": len(rows),
                "suggestion": suggestion,
                "sample_results": rows[:3] if rows else [],
                "columns": columns
            }
            
        except Exception as e:
            console.print(f"  [red]❌ Query failed: {e}[/red]")
            if self.verbose:
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return {
                "query": "detect_anomalies.esql",
                "status": "ERROR",
                "error": str(e)
            }
    
    def test_correlate_root_causes(self) -> Dict[str, Any]:
        """Test root cause correlation query"""
        console.print("\n[bold cyan]━━━ Testing: correlate_root_causes.esql ━━━[/bold cyan]")
        
        # First, get a historical incident
        try:
            incident_query = {
                "size": 1,
                "sort": [{"@timestamp": "desc"}],
                "query": {"match_all": {}}
            }
            
            incidents = self.es.search(index="incidentiq-incidents", body=incident_query)
            
            if not incidents['hits']['hits']:
                console.print("  [yellow]⚠️  No historical incidents found - skipping test[/yellow]")
                return {
                    "query": "correlate_root_causes.esql",
                    "status": "SKIP",
                    "reason": "No historical incidents available"
                }
            
            incident = incidents['hits']['hits'][0]['_source']
            incident_id = incident.get('incident_id', 'UNKNOWN')
            incident_time = incident.get('detected_at', incident.get('@timestamp'))
            incident_service = incident.get('service')
            
            console.print(f"  Using incident: [cyan]{incident_id}[/cyan]")
            console.print(f"  Service: [cyan]{incident_service}[/cyan]")
            console.print(f"  Time: [cyan]{incident_time}[/cyan]")
            
        except Exception as e:
            console.print(f"  [yellow]⚠️  Could not fetch incidents: {e}[/yellow]")
            return {
                "query": "correlate_root_causes.esql",
                "status": "SKIP",
                "error": str(e)
            }
        
        # Load and execute query
        try:
            query = self.load_query("correlate_root_causes.esql")
        except FileNotFoundError:
            return {
                "query": "correlate_root_causes.esql",
                "status": "SKIP",
                "error": "Query file not found"
            }
        
        # Replace variables
        query = query.replace("$incident_start", incident_time)
        query = query.replace("$affected_service", incident_service)
        query = query.replace("$lookback_minutes", "30")
        
        try:
            result = self.es.esql.query(query=query)
            rows = result.get('values', [])
            columns = [col['name'] for col in result.get('columns', [])]
            
            console.print(f"  ✓ Query executed successfully")
            console.print(f"  ✓ Services analyzed: {len(rows)}")
            
            if rows and len(rows) > 0:
                # Check if top service matches incident
                service_idx = columns.index('service') if 'service' in columns else 0
                top_service = rows[0][service_idx] if rows else None
                
                if top_service == incident_service:
                    console.print(f"  [green]✓ Correctly identified root cause: {top_service}[/green]")
                    status = "PASS"
                    suggestion = "Root cause correlation is working correctly"
                else:
                    console.print(f"  [yellow]⚠️  Top service: {top_service}, Expected: {incident_service}[/yellow]")
                    status = "PARTIAL"
                    suggestion = f"Expected {incident_service} but got {top_service} - may need tuning"
                
                # Show results table
                table = Table(title="Root Cause Analysis Results", show_lines=True)
                for col in columns[:min(5, len(columns))]:
                    table.add_column(col, overflow="fold")
                
                for row in rows[:min(5, len(rows))]:
                    table.add_row(*[str(val) for val in row[:min(5, len(columns))]])
                
                console.print(table)
            else:
                console.print("  [red]❌ No results returned[/red]")
                status = "FAIL"
                suggestion = "Query returned no results - check data availability"
                top_service = None
            
            return {
                "query": "correlate_root_causes.esql",
                "status": status,
                "services_found": len(rows),
                "top_service": top_service,
                "expected_service": incident_service,
                "suggestion": suggestion,
                "incident_tested": incident_id
            }
            
        except Exception as e:
            console.print(f"  [red]❌ Query failed: {e}[/red]")
            if self.verbose:
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return {
                "query": "correlate_root_causes.esql",
                "status": "ERROR",
                "error": str(e)
            }
    
    def test_analyze_trends(self) -> Dict[str, Any]:
        """Test trend analysis query"""
        console.print("\n[bold cyan]━━━ Testing: analyze_trends.esql ━━━[/bold cyan]")
        
        try:
            query = self.load_query("analyze_trends.esql")
        except FileNotFoundError:
            return {
                "query": "analyze_trends.esql",
                "status": "SKIP",
                "error": "Query file not found"
            }
        
        # Replace variables
        query = query.replace("$lookback_hours", "24")
        query = query.replace("$bucket_interval", "1h")
        
        if self.verbose:
            console.print(f"[dim]Query parameters: lookback=24h, bucket=1h[/dim]")
        
        try:
            result = self.es.esql.query(query=query)
            rows = result.get('values', [])
            columns = [col['name'] for col in result.get('columns', [])]
            
            console.print(f"  ✓ Query executed successfully")
            console.print(f"  ✓ Data points: {len(rows)}")
            
            # Should have roughly: 5 services * 24 hours = ~120 rows
            # But could vary based on grouping
            expected_min = 20
            expected_max = 300
            
            if expected_min <= len(rows) <= expected_max:
                console.print(f"  [green]✓ Data volume looks good ({len(rows)} rows)[/green]")
                status = "PASS"
                suggestion = "Trend analysis returning reasonable data volume"
            elif len(rows) > expected_max:
                console.print(f"  [yellow]⚠️  High data volume: {len(rows)} rows[/yellow]")
                status = "PARTIAL"
                suggestion = "Consider increasing bucket interval to reduce data points"
            else:
                console.print(f"  [yellow]⚠️  Low data volume: {len(rows)} rows[/yellow]")
                status = "PARTIAL"
                suggestion = "May need more historical data or smaller bucket interval"
            
            # Show sample results
            if rows and len(rows) > 0:
                table = Table(title="Sample Trend Data", show_lines=True)
                for col in columns[:min(7, len(columns))]:
                    table.add_column(col, overflow="fold")
                
                for row in rows[:min(5, len(rows))]:
                    table.add_row(*[str(val)[:20] for val in row[:min(7, len(columns))]])
                
                console.print(table)
            
            return {
                "query": "analyze_trends.esql",
                "status": status,
                "data_points": len(rows),
                "suggestion": suggestion,
                "columns": columns
            }
            
        except Exception as e:
            console.print(f"  [red]❌ Query failed: {e}[/red]")
            if self.verbose:
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return {
                "query": "analyze_trends.esql",
                "status": "ERROR",
                "error": str(e)
            }
    
    def test_calculate_baselines(self) -> Dict[str, Any]:
        """Test baseline calculation query"""
        console.print("\n[bold cyan]━━━ Testing: calculate_baselines.esql ━━━[/bold cyan]")
        
        try:
            query = self.load_query("calculate_baselines.esql")
        except FileNotFoundError:
            return {
                "query": "calculate_baselines.esql",
                "status": "SKIP",
                "error": "Query file not found"
            }
        
        # Replace variables
        query = query.replace("$lookback_days", "7")
        
        if self.verbose:
            console.print(f"[dim]Query parameters: lookback=7 days[/dim]")
        
        try:
            result = self.es.esql.query(query=query)
            rows = result.get('values', [])
            columns = [col['name'] for col in result.get('columns', [])]
            
            console.print(f"  ✓ Query executed successfully")
            console.print(f"  ✓ Services with baselines: {len(rows)}")
            
            # Determine status
            if len(rows) == 5:
                console.print("  [green]✓ All 5 services have baselines[/green]")
                status = "PASS"
                suggestion = "Baseline calculation working for all services"
            elif len(rows) > 0:
                console.print(f"  [yellow]⚠️  Only {len(rows)}/5 services have baselines[/yellow]")
                status = "PARTIAL"
                suggestion = f"Missing baselines for {5 - len(rows)} services - check data availability"
            else:
                console.print("  [red]❌ No baselines calculated[/red]")
                status = "FAIL"
                suggestion = "No baseline data available - check logs/metrics exist"
            
            # Compare with existing baselines
            try:
                existing = self.es.search(
                    index="baselines-services",
                    body={"size": 10, "query": {"match_all": {}}}
                )
                
                if existing['hits']['hits']:
                    console.print(f"  ✓ Found {len(existing['hits']['hits'])} existing baselines for comparison")
                    
                    # Show comparison table
                    if rows:
                        table = Table(title="Baseline Comparison (Calculated vs Existing)", show_lines=True)
                        table.add_column("Service")
                        table.add_column("Error Mean (New)")
                        table.add_column("Error Mean (Existing)")
                        table.add_column("Difference %")
                        
                        service_idx = columns.index('service') if 'service' in columns else 0
                        error_mean_idx = next((i for i, col in enumerate(columns) if 'error' in col.lower() and 'mean' in col.lower()), 1)
                        
                        for row in rows[:5]:
                            service = row[service_idx]
                            new_mean = float(row[error_mean_idx]) if error_mean_idx < len(row) else 0
                            
                            # Find matching existing baseline
                            old_baseline = next(
                                (hit['_source'] for hit in existing['hits']['hits'] 
                                 if hit['_source'].get('service') == service),
                                None
                            )
                            
                            if old_baseline:
                                old_mean = float(old_baseline.get('baseline_error_mean', 0))
                                diff_pct = ((new_mean - old_mean) / old_mean * 100) if old_mean > 0 else 0
                                
                                diff_color = "green" if abs(diff_pct) < 20 else "yellow" if abs(diff_pct) < 50 else "red"
                                
                                table.add_row(
                                    service,
                                    f"{new_mean:.4f}",
                                    f"{old_mean:.4f}",
                                    f"[{diff_color}]{diff_pct:+.1f}%[/{diff_color}]"
                                )
                            else:
                                table.add_row(service, f"{new_mean:.4f}", "N/A", "N/A")
                        
                        console.print(table)
            except Exception as e:
                if self.verbose:
                    console.print(f"[dim]Could not compare with existing baselines: {e}[/dim]")
            
            # Show calculated baselines
            if rows:
                table = Table(title="Newly Calculated Baselines", show_lines=True)
                for col in columns[:min(8, len(columns))]:
                    table.add_column(col, overflow="fold")
                
                for row in rows:
                    table.add_row(*[str(val)[:25] if isinstance(val, str) else f"{val:.4f}" if isinstance(val, float) else str(val) for val in row[:min(8, len(columns))]])
                
                console.print(table)
            
            return {
                "query": "calculate_baselines.esql",
                "status": status,
                "services_calculated": len(rows),
                "suggestion": suggestion,
                "columns": columns
            }
            
        except Exception as e:
            console.print(f"  [red]❌ Query failed: {e}[/red]")
            if self.verbose:
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return {
                "query": "calculate_baselines.esql",
                "status": "ERROR",
                "error": str(e)
            }
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all query tests"""
        console.print(Panel.fit(
            "[bold white]ES|QL Query Comprehensive Testing Suite[/bold white]\n"
            "[dim]Testing all ES|QL queries with real production data[/dim]",
            border_style="cyan",
            padding=(1, 2)
        ))
        
        # Run all tests
        self.results['detect_anomalies'] = self.test_detect_anomalies()
        self.results['correlate_root_causes'] = self.test_correlate_root_causes()
        self.results['analyze_trends'] = self.test_analyze_trends()
        self.results['calculate_baselines'] = self.test_calculate_baselines()
        
        # Generate summary
        self._print_summary()
        
        return self.results
    
    def _print_summary(self):
        """Print test summary"""
        console.print("\n" + "="*70)
        console.print("[bold white]TEST SUMMARY[/bold white]")
        console.print("="*70)
        
        summary_table = Table(show_header=True, header_style="bold cyan", show_lines=True)
        summary_table.add_column("Query", style="cyan", width=30)
        summary_table.add_column("Status", width=10)
        summary_table.add_column("Details", overflow="fold")
        
        for query_name, result in self.results.items():
            status = result.get('status', 'UNKNOWN')
            status_emoji = {
                'PASS': '✓',
                'PARTIAL': '⚠️',
                'FAIL': '✗',
                'ERROR': '✗',
                'SKIP': '○'
            }.get(status, '?')
            
            status_color = {
                'PASS': 'green',
                'PARTIAL': 'yellow',
                'FAIL': 'red',
                'ERROR': 'red',
                'SKIP': 'dim'
            }.get(status, 'white')
            
            # Build details string
            details = []
            if 'suggestion' in result:
                details.append(result['suggestion'])
            if 'error' in result:
                details.append(f"Error: {result['error']}")
            if 'anomalies_found' in result:
                details.append(f"Anomalies: {result['anomalies_found']}")
            if 'services_found' in result:
                details.append(f"Services: {result['services_found']}")
            if 'data_points' in result:
                details.append(f"Data points: {result['data_points']}")
            
            details_str = " | ".join(details) if details else "No additional details"
            
            summary_table.add_row(
                query_name.replace('_', ' ').title(),
                f"[{status_color}]{status_emoji} {status}[/{status_color}]",
                details_str
            )
        
        console.print(summary_table)
        
        # Overall status
        passed = sum(1 for r in self.results.values() if r.get('status') == 'PASS')
        partial = sum(1 for r in self.results.values() if r.get('status') == 'PARTIAL')
        failed = sum(1 for r in self.results.values() if r.get('status') in ['FAIL', 'ERROR'])
        skipped = sum(1 for r in self.results.values() if r.get('status') == 'SKIP')
        total = len(self.results)
        
        console.print(f"\n[bold]Results:[/bold] {passed}/{total} passed, {partial} partial, {failed} failed, {skipped} skipped")
        
        if passed == total:
            console.print("\n[bold green]✅ All tests passed! ES|QL queries are working correctly.[/bold green]")
        elif passed + partial == total:
            console.print("\n[bold yellow]⚠️  Tests passed with warnings. Review suggestions above.[/bold yellow]")
        else:
            console.print("\n[bold red]❌ Some tests failed. Review errors above and fix queries.[/bold red]")


def main():
    parser = argparse.ArgumentParser(description="Test ES|QL queries comprehensively")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--tune", action="store_true", help="Auto-tune thresholds (future feature)")
    
    args = parser.parse_args()
    
    if args.tune:
        console.print("[yellow]⚠️  Auto-tuning not yet implemented[/yellow]")
    
    # Create tests directory if needed
    os.makedirs('tests', exist_ok=True)
    
    # Run tests
    tester = ESQLQueryTester(verbose=args.verbose)
    results = tester.run_all_tests()
    
    # Save results
    output_file = 'tests/esql_test_results.json'
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    console.print(f"\n💾 Detailed results saved to [cyan]{output_file}[/cyan]")
    
    # Exit with appropriate code
    all_passed = all(r.get('status') in ['PASS', 'SKIP'] for r in results.values())
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
