#!/usr/bin/env python3
"""
Slack Bot - Incident notifications and approvals

Usage:
    python src/integrations/slack_bot.py --test
    # Or import and use in other scripts
"""

import os
import sys
import time
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent))

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False

from rich.console import Console

load_dotenv()
console = Console()


class SlackBot:
    """Slack bot for IncidentIQ"""
    
    def __init__(self, verbose: bool = True):
        """
        Initialize Slack bot
        
        Args:
            verbose: Print detailed output
        """
        self.verbose = verbose
        
        if not SLACK_AVAILABLE:
            if self.verbose:
                console.print("[yellow]⚠️  Slack SDK not available - install slack_sdk package[/yellow]")
            self.client = None
            return
        
        token = os.getenv("SLACK_BOT_TOKEN")
        if not token:
            if self.verbose:
                console.print("[yellow]⚠️  SLACK_BOT_TOKEN not set in .env - Slack disabled[/yellow]")
            self.client = None
            return
        
        self.client = WebClient(token=token)
        self.channel = os.getenv("SLACK_INCIDENTS_CHANNEL", "#incidents")
        
        # Verify connection
        try:
            auth_test = self.client.auth_test()
            self.bot_user_id = auth_test['user_id']
            
            if self.verbose:
                console.print(f"[green]✅ Slack bot connected: {auth_test['user']}[/green]")
        except SlackApiError as e:
            console.print(f"[red]❌ Slack connection failed: {e.response['error']}[/red]")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Slack is available and configured"""
        return self.client is not None
    
    def post_incident_detected(
        self,
        incident_id: str,
        service: str,
        error_type: str,
        severity: str
    ) -> Optional[str]:
        """
        Post notification when incident is detected
        
        Returns:
            Message timestamp (for threading) or None
        """
        if not self.is_available():
            if self.verbose:
                console.print(f"[blue]💬 Slack → {self.channel}: 🚨 {incident_id} detected ({severity})[/blue]")
            return None
        
        severity_emoji = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
            "LOW": "🟢"
        }.get(severity, "⚪")
        
        text = f"{severity_emoji} *Incident Detected: {incident_id}*"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 {incident_id} - {severity}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:*\n{service}"},
                    {"type": "mrkdwn", "text": f"*Error Type:*\n{error_type}"},
                    {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                    {"type": "mrkdwn", "text": f"*Status:*\nAnalyzing..."}
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Detected by Detective Agent at {time.strftime('%H:%M:%S')}"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks
            )
            
            if self.verbose:
                console.print(f"[cyan]📱 Posted to Slack: {incident_id}[/cyan]")
            
            return response['ts']  # Message timestamp for threading
            
        except SlackApiError as e:
            console.print(f"[red]❌ Failed to post to Slack: {e.response['error']}[/red]")
            return None
    
    def post_analysis_complete(
        self,
        incident_id: str,
        root_cause: str,
        recommended_workflow: str,
        confidence: float,
        thread_ts: Optional[str] = None
    ):
        """Post analysis results"""
        
        if not self.is_available():
            if self.verbose:
                console.print(f"[blue]💬 Slack → {self.channel}: 🔬 Analysis complete: {recommended_workflow} ({confidence:.0%})[/blue]")
            return
        
        confidence_emoji = "🟢" if confidence >= 0.8 else "🟡" if confidence >= 0.5 else "🔴"
        
        text = f"Analysis complete for {incident_id}"
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🔬 Analysis Complete*\n\n"
                            f"*Root Cause:* {root_cause}\n"
                            f"*Recommended Fix:* `{recommended_workflow}`\n"
                            f"*Confidence:* {confidence_emoji} {confidence:.0%}"
                }
            }
        ]
        
        try:
            self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts
            )
            
            if self.verbose:
                console.print(f"[cyan]📱 Posted analysis update[/cyan]")
                
        except SlackApiError as e:
            console.print(f"[yellow]⚠️  Failed to post analysis: {e.response['error']}[/yellow]")
    
    def request_approval(
        self,
        incident_id: str,
        workflow_name: str,
        service: str,
        risk_level: str,
        timeout_seconds: int = 600,
        thread_ts: Optional[str] = None
    ) -> bool:
        """
        Request approval for high-risk workflow
        
        Returns:
            True if approved, False if denied or timeout
        """
        if not self.is_available():
            # In testing mode, simulate approval after short delay
            if self.verbose:
                console.print(f"[blue]💬 Slack → {self.channel}: ⚠️ Approval request: {workflow_name} for {incident_id}[/blue]")
                console.print(f"[yellow]⏸️  Simulating approval (no Slack configured)...[/yellow]")
                time.sleep(2)  # Simulate user thinking time
                console.print(f"[green]✅ Auto-approved (simulation mode)[/green]")
            return True  # Auto-approve when Slack not available
        
        text = f"⚠️ Approval Required: {incident_id}"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "⚠️ HIGH RISK - Approval Required",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Incident:* {incident_id}\n"
                            f"*Workflow:* `{workflow_name}`\n"
                            f"*Service:* {service}\n"
                            f"*Risk Level:* {risk_level}\n\n"
                            f"React with ✅ to approve or ❌ to deny\n"
                            f"Timeout: {timeout_seconds // 60} minutes"
                }
            }
        ]
        
        try:
            response = self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts
            )
            
            message_ts = response['ts']
            
            # Add emoji reactions as buttons
            self.client.reactions_add(
                channel=self.channel,
                name="white_check_mark",
                timestamp=message_ts
            )
            self.client.reactions_add(
                channel=self.channel,
                name="x",
                timestamp=message_ts
            )
            
            if self.verbose:
                console.print(f"[yellow]⏸️  Waiting for approval (timeout: {timeout_seconds}s)...[/yellow]")
            
            # Poll for reactions
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                try:
                    # Get message reactions
                    reactions_response = self.client.reactions_get(
                        channel=self.channel,
                        timestamp=message_ts
                    )
                    
                    reactions = reactions_response.get('message', {}).get('reactions', [])
                    
                    for reaction in reactions:
                        # Check for approval (✅)
                        if reaction['name'] == 'white_check_mark' and reaction['count'] > 1:  # >1 because bot adds it
                            # Find who approved
                            users = reaction.get('users', [])
                            approvers = [u for u in users if u != self.bot_user_id]
                            
                            if approvers:
                                if self.verbose:
                                    console.print(f"[green]✅ Approved by user: {approvers[0]}[/green]")
                                
                                # Update message
                                self.client.chat_update(
                                    channel=self.channel,
                                    ts=message_ts,
                                    text="✅ APPROVED",
                                    blocks=[
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"✅ *APPROVED*\n\n"
                                                        f"Workflow `{workflow_name}` approved for execution"
                                            }
                                        }
                                    ]
                                )
                                
                                return True
                        
                        # Check for denial (❌)
                        if reaction['name'] == 'x' and reaction['count'] > 1:
                            users = reaction.get('users', [])
                            deniers = [u for u in users if u != self.bot_user_id]
                            
                            if deniers:
                                if self.verbose:
                                    console.print(f"[red]❌ Denied by user: {deniers[0]}[/red]")
                                
                                # Update message
                                self.client.chat_update(
                                    channel=self.channel,
                                    ts=message_ts,
                                    text="❌ DENIED",
                                    blocks=[
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"❌ *DENIED*\n\n"
                                                        f"Workflow execution cancelled - manual intervention required"
                                            }
                                        }
                                    ]
                                )
                                
                                return False
                    
                except SlackApiError:
                    pass
                
                time.sleep(5)  # Poll every 5 seconds
            
            # Timeout
            if self.verbose:
                console.print(f"[yellow]⏱️  Approval timeout - defaulting to DENY[/yellow]")
            
            self.client.chat_update(
                channel=self.channel,
                ts=message_ts,
                text="⏱️ TIMEOUT",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⏱️ *TIMEOUT*\n\nNo approval received - workflow cancelled"
                        }
                    }
                ]
            )
            
            return False
            
        except SlackApiError as e:
            console.print(f"[red]❌ Failed to request approval: {e.response['error']}[/red]")
            return False
    
    def post_workflow_executing(
        self,
        incident_id: str,
        workflow_name: str,
        estimated_duration: int,
        thread_ts: Optional[str] = None
    ):
        """Post notification when workflow starts executing"""
        
        if not self.is_available():
            if self.verbose:
                console.print(f"[blue]💬 Slack → {self.channel}: ⚡ Executing {workflow_name} for {incident_id}[/blue]")
            return
        
        text = f"⚡ Executing workflow for {incident_id}"
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*⚡ Workflow Executing*\n\n"
                            f"*Workflow:* `{workflow_name}`\n"
                            f"*Estimated Duration:* {estimated_duration}s\n"
                            f"*Status:* In progress..."
                }
            }
        ]
        
        try:
            self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts
            )
            
            if self.verbose:
                console.print(f"[cyan]📱 Posted workflow execution update[/cyan]")
                
        except SlackApiError as e:
            console.print(f"[yellow]⚠️  Failed to post execution: {e.response['error']}[/yellow]")
    
    def post_resolution(
        self,
        incident_id: str,
        workflow_name: str,
        duration_seconds: int,
        success: bool,
        thread_ts: Optional[str] = None
    ):
        """Post resolution notification"""
        
        if not self.is_available():
            status = "resolved ✅" if success else "failed ❌"
            if self.verbose:
                console.print(f"[blue]💬 Slack → {self.channel}: {incident_id} {status} ({duration_seconds}s)[/blue]")
            return
        
        if success:
            emoji = "✅"
            status_text = "Resolved Successfully"
            color = "good"
        else:
            emoji = "❌"
            status_text = "Resolution Failed"
            color = "danger"
        
        text = f"{emoji} {incident_id} - {status_text}"
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{emoji} {status_text}*\n\n"
                            f"*Incident:* {incident_id}\n"
                            f"*Workflow:* `{workflow_name}`\n"
                            f"*Duration:* {duration_seconds}s\n"
                            f"*Auto-resolved:* {'Yes ✨' if success else 'No - manual required'}"
                }
            }
        ]
        
        if success:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💤 Sweet dreams! Your incidents are being handled."
                    }
                ]
            })
        
        try:
            self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts
            )
            
            if self.verbose:
                console.print(f"[cyan]📱 Posted resolution notification[/cyan]")
                
        except SlackApiError as e:
            console.print(f"[yellow]⚠️  Failed to post resolution: {e.response['error']}[/yellow]")
    
    def post_escalation(
        self,
        incident_id: str,
        reason: str,
        thread_ts: Optional[str] = None
    ):
        """Post escalation notification"""
        
        if not self.is_available():
            if self.verbose:
                console.print(f"[blue]💬 Slack → {self.channel}: 🚨 {incident_id} escalated: {reason}[/blue]")
            return
        
        text = f"🚨 Incident Escalated: {incident_id}"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 ESCALATION - Manual Intervention Required",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Incident:* {incident_id}\n"
                            f"*Reason:* {reason}\n"
                            f"*Action Required:* Manual investigation needed"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "@oncall @sre-team Please investigate immediately"
                    }
                ]
            }
        ]
        
        try:
            self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts
            )
            
            if self.verbose:
                console.print(f"[cyan]📱 Posted escalation notification[/cyan]")
                
        except SlackApiError as e:
            console.print(f"[yellow]⚠️  Failed to post escalation: {e.response['error']}[/yellow]")


def main():
    """Test Slack bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Slack Bot Test")
    parser.add_argument("--test", action="store_true", help="Run test notifications")
    parser.add_argument("--approval-test", action="store_true", help="Test approval workflow")
    
    args = parser.parse_args()
    
    console.print(Panel.fit(
        "[bold blue]🤖 IncidentIQ - Slack Bot[/bold blue]",
        subtitle="Incident Notifications & Approvals"
    ))
    
    bot = SlackBot()
    
    if args.test:
        console.print("\n[bold]Testing Slack Bot...[/bold]\n")
        
        # Test 1: Incident detected
        console.print("1️⃣  Testing incident detection notification...")
        thread_ts = bot.post_incident_detected(
            incident_id="INC-TEST-001",
            service="test-service",
            error_type="TestException",
            severity="HIGH"
        )
        time.sleep(2)
        
        # Test 2: Analysis complete
        console.print("2️⃣  Testing analysis notification...")
        bot.post_analysis_complete(
            incident_id="INC-TEST-001",
            root_cause="Test error for demonstration",
            recommended_workflow="safe_service_restart",
            confidence=0.95,
            thread_ts=thread_ts
        )
        time.sleep(2)
        
        # Test 3: Workflow executing
        console.print("3️⃣  Testing workflow execution notification...")
        bot.post_workflow_executing(
            incident_id="INC-TEST-001",
            workflow_name="safe_service_restart",
            estimated_duration=180,
            thread_ts=thread_ts
        )
        time.sleep(2)
        
        # Test 4: Resolution
        console.print("4️⃣  Testing resolution notification...")
        bot.post_resolution(
            incident_id="INC-TEST-001",
            workflow_name="safe_service_restart",
            duration_seconds=180,
            success=True,
            thread_ts=thread_ts
        )
        
        console.print("\n[green]✅ Test complete! Check #incidents channel in Slack[/green]")
    
    elif args.approval_test:
        console.print("\n[bold]Testing Approval Workflow...[/bold]\n")
        
        approved = bot.request_approval(
            incident_id="INC-APPROVAL-TEST",
            workflow_name="rollback_deployment",
            service="payment-service",
            risk_level="HIGH",
            timeout_seconds=30  # Short timeout for testing
        )
        
        if approved:
            console.print("\n[green]✅ Workflow was approved![/green]")
        else:
            console.print("\n[red]❌ Workflow was denied or timed out[/red]")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    from rich.panel import Panel
    main()