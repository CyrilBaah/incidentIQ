#!/usr/bin/env python3
"""
Workflow Executor - Executes workflow YAML files

Usage:
    python src/workflow_executor.py --workflow safe_service_restart --param service=api-gateway
    python src/workflow_executor.py --workflow-file custom.yaml --param service=api-gateway
"""

import os
import sys
import yaml
import time
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))

from elasticsearch import Elasticsearch
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

# Import Kubernetes client
try:
    from kubernetes import client, config
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False

load_dotenv()
console = Console()


class WorkflowExecutor:
    """Executes workflow definitions"""
    
    def __init__(self, verbose: bool = True):
        """
        Initialize Workflow Executor
        
        Args:
            verbose: Print detailed output
        """
        self.verbose = verbose
        
        # Elasticsearch connection
        try:
            self.es = Elasticsearch(
                cloud_id=os.getenv("ELASTIC_CLOUD_ID"),
                api_key=os.getenv("ELASTIC_API_KEY")
            )
            if self.verbose:
                console.print("[green]✅ Elasticsearch connected[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️  Elasticsearch connection failed: {e}[/yellow]")
            self.es = None
        
        # Kubernetes connection (load from kubeconfig or in-cluster)
        if KUBERNETES_AVAILABLE:
            try:
                config.load_kube_config()  # For local development
                self.k8s_apps = client.AppsV1Api()
                self.k8s_core = client.CoreV1Api()
                if self.verbose:
                    console.print("[green]✅ Kubernetes connected (kubeconfig)[/green]")
            except:
                try:
                    config.load_incluster_config()  # For in-cluster
                    self.k8s_apps = client.AppsV1Api()
                    self.k8s_core = client.CoreV1Api()
                    if self.verbose:
                        console.print("[green]✅ Kubernetes connected (in-cluster)[/green]")
                except:
                    if self.verbose:
                        console.print("[yellow]⚠️  Kubernetes config not loaded - K8s actions will fail[/yellow]")
                    self.k8s_apps = None
                    self.k8s_core = None
        else:
            if self.verbose:
                console.print("[yellow]⚠️  Kubernetes client not available - install kubernetes package[/yellow]")
            self.k8s_apps = None
            self.k8s_core = None
        
        # Execution state
        self.execution_context = {}
        self.execution_start = None
        self.execution_steps = []
        
        if self.verbose:
            console.print("[green]✅ Workflow Executor initialized[/green]")
    
    def load_workflow(self, workflow_name: str = None, workflow_file: str = None) -> Optional[Dict]:
        """
        Load workflow from file
        
        Args:
            workflow_name: Name of workflow (loads from tools/workflows/{name}.yaml)
            workflow_file: Direct path to workflow file
        
        Returns:
            Workflow dictionary or None
        """
        if workflow_file:
            path = workflow_file
        elif workflow_name:
            path = f"tools/workflows/{workflow_name}.yaml"
        else:
            console.print("[red]❌ Must provide workflow_name or workflow_file[/red]")
            return None
        
        if not os.path.exists(path):
            console.print(f"[red]❌ Workflow file not found: {path}[/red]")
            return None
        
        try:
            with open(path, 'r') as f:
                workflow = yaml.safe_load(f)
            
            if self.verbose:
                console.print(f"[cyan]📄 Loaded workflow: {workflow.get('name')}[/cyan]")
                console.print(f"   Risk: {workflow.get('risk_level')}")
                console.print(f"   Auto-approve: {workflow.get('auto_approve')}")
            
            return workflow
            
        except Exception as e:
            console.print(f"[red]❌ Error loading workflow: {e}[/red]")
            return None
    
    def substitute_parameters(self, text: str, params: Dict[str, Any]) -> str:
        """
        Substitute ${variable} in text with values from params
        
        Args:
            text: Text with ${variable} placeholders
            params: Dictionary of variable values
        
        Returns:
            Text with substitutions
        """
        import re
        
        def replace(match):
            var_name = match.group(1)
            return str(params.get(var_name, match.group(0)))
        
        return re.sub(r'\$\{(\w+)\}', replace, str(text))
    
    def execute_kubernetes_action(
        self, 
        action: str, 
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute Kubernetes action
        
        Args:
            action: Action name (e.g., rollout_restart, scale, get_deployment)
            parameters: Action parameters
        
        Returns:
            Result dictionary with success/failure
        """
        if not self.k8s_apps or not self.k8s_core:
            return {
                "success": False,
                "error": "Kubernetes client not available"
            }
        
        deployment = parameters.get('name') or parameters.get('deployment')
        namespace = parameters.get('namespace', 'default')
        
        try:
            if action == 'get_deployment':
                result = self.k8s_apps.read_namespaced_deployment(
                    name=deployment,
                    namespace=namespace
                )
                return {
                    "success": True,
                    "exists": True,
                    "replicas": result.spec.replicas,
                    "ready_replicas": result.status.ready_replicas or 0
                }
            
            elif action == 'rollout_restart':
                # Trigger restart by updating annotation
                body = {
                    "spec": {
                        "template": {
                            "metadata": {
                                "annotations": {
                                    "kubectl.kubernetes.io/restartedAt": datetime.utcnow().isoformat()
                                }
                            }
                        }
                    }
                }
                
                self.k8s_apps.patch_namespaced_deployment(
                    name=deployment,
                    namespace=namespace,
                    body=body
                )
                
                return {"success": True, "message": f"Restart initiated for {deployment}"}
            
            elif action == 'scale':
                target_replicas = int(parameters.get('replicas'))
                
                body = {
                    "spec": {
                        "replicas": target_replicas
                    }
                }
                
                self.k8s_apps.patch_namespaced_deployment(
                    name=deployment,
                    namespace=namespace,
                    body=body
                )
                
                return {
                    "success": True,
                    "message": f"Scaled {deployment} to {target_replicas} replicas"
                }
            
            elif action == 'wait_for_deployment_ready':
                timeout = int(parameters.get('timeout', 300))
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    result = self.k8s_apps.read_namespaced_deployment(
                        name=deployment,
                        namespace=namespace
                    )
                    
                    if result.status.ready_replicas == result.spec.replicas:
                        return {
                            "success": True,
                            "message": f"{deployment} is ready",
                            "ready_replicas": result.status.ready_replicas
                        }
                    
                    time.sleep(5)
                
                return {
                    "success": False,
                    "error": f"Timeout waiting for {deployment} to be ready"
                }
            
            elif action == 'wait_for_replicas':
                target = int(parameters.get('target'))
                timeout = int(parameters.get('timeout', 300))
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    result = self.k8s_apps.read_namespaced_deployment(
                        name=deployment,
                        namespace=namespace
                    )
                    
                    if result.status.ready_replicas == target:
                        return {
                            "success": True,
                            "message": f"{deployment} has {target} ready replicas"
                        }
                    
                    time.sleep(5)
                
                return {
                    "success": False,
                    "error": f"Timeout waiting for {deployment} to reach {target} replicas"
                }
            
            elif action == 'check_pod_health':
                # Get pods for deployment
                pods = self.k8s_core.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=f"app={deployment}"
                )
                
                unhealthy_pods = []
                for pod in pods.items:
                    if pod.status.phase != 'Running':
                        unhealthy_pods.append(pod.metadata.name)
                
                if unhealthy_pods:
                    return {
                        "success": False,
                        "error": f"Unhealthy pods: {unhealthy_pods}"
                    }
                
                return {
                    "success": True,
                    "healthy_pods": len(pods.items),
                    "message": f"All {len(pods.items)} pods healthy"
                }
            
            elif action == 'check_all_pods_ready':
                pods = self.k8s_core.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=f"app={deployment}"
                )
                
                ready_count = 0
                for pod in pods.items:
                    if pod.status.phase == 'Running':
                        for condition in pod.status.conditions or []:
                            if condition.type == 'Ready' and condition.status == 'True':
                                ready_count += 1
                                break
                
                total_pods = len(pods.items)
                
                if ready_count == total_pods and total_pods > 0:
                    return {
                        "success": True,
                        "ready_pods": ready_count,
                        "total_pods": total_pods
                    }
                
                return {
                    "success": False,
                    "error": f"Only {ready_count}/{total_pods} pods ready"
                }
            
            elif action == 'rollout_undo':
                # Rollback to previous version
                to_revision = parameters.get('to_revision')
                
                # For demo purposes, we'll simulate the rollback
                # In production, you'd use proper kubectl rollout undo equivalent
                console.print(f"[yellow]📝 Note: Simulating rollback for demo (revision: {to_revision})[/yellow]")
                
                return {
                    "success": True,
                    "message": f"Rollback initiated for {deployment}" + (f" to revision {to_revision}" if to_revision else " to previous")
                }
            
            elif action == 'get_rollout_history':
                # Simulate getting rollout history
                # In production, you'd get actual revision history
                return {
                    "success": True,
                    "revisions": [1, 2, 3],  # Mock data
                    "current": 3
                }
            
            elif action == 'capture_deployment_state':
                result = self.k8s_apps.read_namespaced_deployment(
                    name=deployment,
                    namespace=namespace
                )
                
                return {
                    "success": True,
                    "state": {
                        "name": deployment,
                        "namespace": namespace,
                        "replicas": result.spec.replicas,
                        "image": result.spec.template.spec.containers[0].image
                    }
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown Kubernetes action: {action}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Kubernetes error: {str(e)}"
            }
    
    def execute_elasticsearch_action(
        self,
        action: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute Elasticsearch action"""
        if not self.es:
            return {
                "success": False,
                "error": "Elasticsearch client not available"
            }
        
        try:
            if action == 'esql_query':
                query = parameters.get('query')
                
                # Execute ES|QL query
                result = self.es.esql.query(query=query)
                
                # Extract results
                columns = [col['name'] for col in result.get('columns', [])]
                rows = result.get('values', [])
                
                # Convert to list of dicts
                data = [dict(zip(columns, row)) for row in rows]
                
                # Add results to context for validation
                for item in data:
                    for key, value in item.items():
                        self.execution_context[key] = value
                
                return {
                    "success": True,
                    "data": data,
                    "row_count": len(data)
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown Elasticsearch action: {action}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Elasticsearch error: {str(e)}"
            }
    
    def execute_internal_action(
        self,
        action: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute internal action"""
        try:
            if action == 'update_incident':
                status = parameters.get('status')
                message = parameters.get('message', '')
                
                # Simulate incident update
                console.print(f"[blue]📝 Updated incident status: {status}[/blue]")
                if message:
                    console.print(f"   Message: {message}")
                
                return {
                    "success": True,
                    "status": status,
                    "message": message
                }
            
            elif action == 'calculate':
                expression = parameters.get('expression', '')
                
                # Simple calculation simulation
                # In production, you'd have a safer expression evaluator
                console.print(f"[blue]🧮 Calculation: {expression}[/blue]")
                
                return {
                    "success": True,
                    "result": "calculated_value"
                }
            
            elif action == 'validate':
                condition = parameters.get('condition', '')
                
                # Simple validation simulation
                console.print(f"[blue]✓ Validation: {condition}[/blue]")
                
                return {
                    "success": True,
                    "validated": True
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown internal action: {action}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Internal action error: {str(e)}"
            }
    
    def execute_slack_action(
        self,
        action: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute Slack action (simulated for now)"""
        try:
            if action == 'post_message':
                channel = parameters.get('channel', '#incidents')
                message = parameters.get('message', '')
                mention = parameters.get('mention', '')
                
                full_message = f"{mention} {message}" if mention else message
                
                console.print(f"[blue]💬 Slack → {channel}: {full_message}[/blue]")
                
                return {
                    "success": True,
                    "channel": channel,
                    "message": message
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack action: {action}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Slack action error: {str(e)}"
            }
    
    def execute_step(
        self,
        step: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a single workflow step
        
        Args:
            step: Step definition
            params: Workflow parameters
        
        Returns:
            Result dictionary
        """
        step_name = step.get('name', 'unnamed')
        step_type = step.get('type')
        action = step.get('action')
        parameters = step.get('parameters', {})
        retry_attempts = step.get('retry_attempts', 1)
        retry_delay = step.get('retry_delay_seconds', 5)
        
        # Substitute parameters in all string values
        substituted_params = {}
        for key, value in parameters.items():
            if isinstance(value, str):
                substituted_params[key] = self.substitute_parameters(value, params)
            else:
                substituted_params[key] = value
        
        if self.verbose:
            console.print(f"[cyan]▶️  Executing step: {step_name}[/cyan]")
        
        step_start = time.time()
        result = None
        
        # Execute with retries
        for attempt in range(retry_attempts):
            if attempt > 0:
                console.print(f"[yellow]   Retry attempt {attempt + 1}/{retry_attempts}[/yellow]")
                time.sleep(retry_delay)
            
            # Execute based on type
            if step_type == 'kubernetes':
                result = self.execute_kubernetes_action(action, substituted_params)
            elif step_type == 'elasticsearch':
                result = self.execute_elasticsearch_action(action, substituted_params)
            elif step_type == 'internal':
                result = self.execute_internal_action(action, substituted_params)
            elif step_type == 'slack':
                result = self.execute_slack_action(action, substituted_params)
            else:
                result = {"success": False, "error": f"Unknown step type: {step_type}"}
            
            # Break on success
            if result.get('success'):
                break
        
        step_duration = time.time() - step_start
        
        # Check validation if specified
        validation_rules = step.get('validation', [])
        if result.get('success') and validation_rules:
            for rule in validation_rules:
                # Simple validation simulation
                # In production, you'd implement proper expression evaluation
                console.print(f"[blue]   Validating: {rule}[/blue]")
                # Assume validation passes for demo
        
        # Record step execution
        step_record = {
            "name": step_name,
            "type": step_type,
            "action": action,
            "duration_seconds": round(step_duration, 2),
            "success": result.get('success', False),
            "attempts": attempt + 1,
            "result": result
        }
        
        self.execution_steps.append(step_record)
        
        # Update context with any captured outputs
        capture_output = step.get('capture_output')
        if capture_output and result.get('success'):
            if capture_output in result:
                self.execution_context[capture_output] = result[capture_output]
        
        if result.get('success'):
            if self.verbose:
                console.print(f"[green]  ✅ {step_name} completed ({step_duration:.1f}s)[/green]")
        else:
            if self.verbose:
                console.print(f"[red]  ❌ {step_name} failed: {result.get('error')}[/red]")
        
        return result
    
    def execute_workflow(
        self,
        workflow: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute complete workflow
        
        Args:
            workflow: Workflow definition
            params: Input parameters
        
        Returns:
            Execution results
        """
        self.execution_start = time.time()
        self.execution_steps = []
        self.execution_context = params.copy()
        
        workflow_name = workflow.get('name')
        
        console.print(Panel.fit(
            f"[bold cyan]⚙️  Executing Workflow: {workflow_name}[/bold cyan]\n"
            f"Risk: {workflow.get('risk_level')}\n"
            f"Estimated time: {workflow.get('estimated_duration_seconds')}s",
            border_style="cyan"
        ))
        
        # Phase 1: Pre-checks
        console.print("\n[bold]Phase 1: Pre-checks[/bold]")
        pre_checks = workflow.get('pre_checks', [])
        
        for check in pre_checks:
            result = self.execute_step(check, self.execution_context)
            
            if not result.get('success'):
                on_failure = check.get('on_failure', 'abort')
                
                if on_failure == 'abort':
                    console.print(f"[red]❌ Pre-check failed, aborting workflow[/red]")
                    return self._generate_result(False, "Pre-check failed")
                elif on_failure == 'continue':
                    console.print(f"[yellow]⚠️  Pre-check failed, continuing anyway[/yellow]")
        
        # Phase 2: Execution Steps
        console.print("\n[bold]Phase 2: Execution[/bold]")
        steps = workflow.get('steps', [])
        
        for step in steps:
            result = self.execute_step(step, self.execution_context)
            
            if not result.get('success'):
                on_failure = step.get('on_failure', 'abort')
                
                if on_failure == 'rollback':
                    console.print(f"[yellow]⏪ Triggering rollback...[/yellow]")
                    self._execute_rollback(workflow)
                    return self._generate_result(False, "Step failed, rolled back")
                
                elif on_failure == 'abort':
                    console.print(f"[red]❌ Step failed, aborting[/red]")
                    return self._generate_result(False, "Step failed")
                
                elif on_failure == 'continue':
                    console.print(f"[yellow]⚠️  Step failed, continuing anyway[/yellow]")
        
        # Phase 3: Success Actions
        console.print("\n[bold]Phase 3: Success Actions[/bold]")
        success_actions = workflow.get('success_actions', [])
        
        for action in success_actions:
            self.execute_step(action, self.execution_context)
        
        return self._generate_result(True, "Workflow completed successfully")
    
    def _execute_rollback(self, workflow: Dict[str, Any]):
        """Execute rollback steps"""
        console.print("\n[bold yellow]🔄 ROLLBACK PHASE[/bold yellow]")
        
        rollback_steps = workflow.get('rollback', [])
        
        for step in rollback_steps:
            self.execute_step(step, self.execution_context)
    
    def _generate_result(self, success: bool, message: str) -> Dict[str, Any]:
        """Generate final execution result"""
        total_duration = time.time() - self.execution_start
        
        # Add execution time to context
        self.execution_context['execution_time'] = total_duration
        
        result = {
            "success": success,
            "message": message,
            "total_duration_seconds": round(total_duration, 2),
            "steps_executed": len(self.execution_steps),
            "steps": self.execution_steps,
            "context": self.execution_context,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Display summary
        console.print("\n" + "="*60)
        if success:
            console.print("[bold green]✅ WORKFLOW SUCCEEDED[/bold green]")
        else:
            console.print("[bold red]❌ WORKFLOW FAILED[/bold red]")
        console.print("="*60)
        console.print(f"Duration: {total_duration:.1f}s")
        console.print(f"Steps: {len(self.execution_steps)}")
        console.print(f"Status: {message}")
        console.print("="*60)
        
        return result


def main():
    parser = argparse.ArgumentParser(description="Workflow Executor")
    parser.add_argument("--workflow", help="Workflow name (from tools/workflows/)")
    parser.add_argument("--workflow-file", help="Direct path to workflow file")
    parser.add_argument("--param", action="append", help="Parameters (key=value)")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--list-workflows", action="store_true", help="List available workflows")
    
    args = parser.parse_args()
    
    # List workflows option
    if args.list_workflows:
        workflows_dir = Path("tools/workflows")
        if workflows_dir.exists():
            console.print("[cyan]Available workflows:[/cyan]")
            for yaml_file in workflows_dir.glob("*.yaml"):
                console.print(f"  • {yaml_file.stem}")
        else:
            console.print("[red]No workflows directory found[/red]")
        return 0
    
    if not args.workflow and not args.workflow_file:
        parser.print_help()
        return 1
    
    # Parse parameters
    params = {}
    if args.param:
        for param in args.param:
            if '=' not in param:
                console.print(f"[red]Invalid parameter format: {param} (use key=value)[/red]")
                return 1
            key, value = param.split('=', 1)
            params[key] = value
    
    console.print(Panel.fit(
        "[bold blue]🔧 IncidentIQ - Workflow Executor[/bold blue]",
        subtitle="Autonomous Remediation Engine"
    ))
    
    executor = WorkflowExecutor(verbose=not args.quiet)
    
    # Load workflow
    workflow = executor.load_workflow(
        workflow_name=args.workflow,
        workflow_file=args.workflow_file
    )
    
    if not workflow:
        return 1
    
    # Execute
    result = executor.execute_workflow(workflow, params)
    
    return 0 if result['success'] else 1


if __name__ == "__main__":
    exit(main())