"""Gradio admin UI for TenderAI BF."""

import os
import threading
import time
from datetime import datetime
from typing import List, Tuple, Optional

import gradio as gr
import httpx

from ..config import settings
from ..logging import get_logger

logger = get_logger(__name__)


class TenderAIUI:
    """Gradio-based admin interface for TenderAI BF."""
    
    def __init__(self, api_url: Optional[str] = None):
        # Priority: parameter > env var > settings > default
        self.api_url = (
            api_url or 
            os.getenv('API_URL') or 
            getattr(settings, 'api_url', None) or 
            'http://localhost:8000'
        )
        self.auth_token: Optional[str] = None
        self.app = None
        self._auto_login()  # Auto-login to API
        self._setup_interface()
    
    def _auto_login(self):
        """Automatically login to API on startup."""
        try:
            url = f"{self.api_url}/api/v1/admin/login"
            data = {
                "username": os.getenv("TENDERAI_ADMIN_USERNAME", "admin"),
                "password": os.getenv("TENDERAI_ADMIN_PASSWORD", "admin123")
            }
            
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    self.auth_token = result.get("access_token")
                    logger.info("UI auto-login successful")
                else:
                    logger.warning(f"UI auto-login failed: {response.status_code}")
        
        except Exception as e:
            logger.warning(f"UI auto-login error: {e}")
    
    def _get_headers(self) -> dict:
        """Get HTTP headers with auth token."""
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers
    
    def _api_request(self, method: str, endpoint: str, **kwargs):
        """Make API request with error handling."""
        url = f"{self.api_url}{endpoint}"
        headers = self._get_headers()
        
        try:
            with httpx.Client(timeout=30.0) as client:
                if method.upper() == "GET":
                    response = client.get(url, headers=headers, **kwargs)
                elif method.upper() == "POST":
                    response = client.post(url, headers=headers, **kwargs)
                elif method.upper() == "PUT":
                    response = client.put(url, headers=headers, **kwargs)
                elif method.upper() == "DELETE":
                    response = client.delete(url, headers=headers, **kwargs)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                response.raise_for_status()
                return response.json() if response.content else {}
        
        except httpx.HTTPStatusError as e:
            logger.error(f"API request failed: {e.response.status_code} - {e.response.text}")
            return {"error": f"API Error: {e.response.status_code}"}
        except Exception as e:
            logger.error(f"API request failed: {str(e)}")
            return {"error": str(e)}
    
    def _setup_interface(self):
        """Set up the Gradio interface."""
        
        with gr.Blocks(
            title="TenderAI BF - Admin Dashboard",
            theme=gr.themes.Soft(),
            css="""
            .status-card { padding: 1rem; margin: 0.5rem; border-radius: 8px; }
            .status-healthy { background-color: #d4edda; border-color: #c3e6cb; }
            .status-unhealthy { background-color: #f8d7da; border-color: #f5c6cb; }
            .metric-card { text-align: center; padding: 1rem; }
            """
        ) as app:
            
            # Header
            gr.Markdown(
                f"""
                # 🔍 TenderAI BF - Admin Dashboard
                **Multi-agent RFP harvester for Burkina Faso**
                
                Version: {settings.app_version} | Environment: {settings.environment}
                """
            )
            
            # Status row
            with gr.Row():
                with gr.Column(scale=1):
                    system_status = gr.HTML(label="System Status")
                    refresh_status_btn = gr.Button("🔄 Refresh Status", variant="secondary")
                
                with gr.Column(scale=1):
                    last_run_info = gr.HTML(label="Last Run Info")
            
            # Main tabs
            with gr.Tabs():
                
                # Dashboard tab
                with gr.TabItem("📊 Dashboard"):
                    with gr.Row():
                        run_now_btn = gr.Button(
                            "🚀 Run Now",
                            variant="primary",
                            size="lg"
                        )
                        
                        rebuild_report_btn = gr.Button(
                            "📄 Rebuild Last Report",
                            variant="secondary"
                        )
                    
                    run_output = gr.HTML(label="Run Output")
                    
                    with gr.Row():
                        with gr.Column():
                            gr.Markdown("### Recent Runs")
                            recent_runs_df = gr.Dataframe(
                                headers=["ID", "Status", "Started", "Duration", "Items"],
                                interactive=False
                            )
                
                # Sources tab
                with gr.TabItem("🌐 Sources"):
                    gr.Markdown("### Active Sources")
                    sources_df = gr.Dataframe(
                        headers=["Name", "Type", "URL", "Rate Limit", "Last Success"],
                        interactive=False
                    )
                    
                    with gr.Row():
                        refresh_sources_btn = gr.Button("🔄 Refresh Sources")
                        test_sources_btn = gr.Button("🧪 Test Sources")
                
                # Reports tab
                with gr.TabItem("📄 Reports"):
                    gr.Markdown("### Download Reports")
                    
                    with gr.Row():
                        report_runs_dropdown = gr.Dropdown(
                            label="Select Run",
                            choices=[],
                            interactive=True
                        )
                        download_report_btn = gr.Button("📥 Download Report")
                    
                    report_preview = gr.HTML(label="Report Preview")
                
                # Settings tab
                with gr.TabItem("⚙️ Settings"):
                    gr.Markdown("### Configuration")
                    
                    with gr.Row():
                        with gr.Column():
                            gr.Markdown("**Email Settings**")
                            email_to = gr.Textbox(
                                label="To Address",
                                value=settings.email.to_address,
                                interactive=True
                            )
                            test_email_btn = gr.Button("📧 Test Email")
                            test_email_result = gr.HTML()
                        
                        with gr.Column():
                            gr.Markdown("**Schedule Settings**")
                            cron_schedule = gr.Textbox(
                                label="Cron Schedule",
                                value=settings.scheduler.cron_schedule,
                                interactive=True
                            )
                            save_settings_btn = gr.Button("💾 Save Settings")
                
                # Logs tab
                with gr.TabItem("📝 Logs"):
                    gr.Markdown("### System Logs")
                    logs_output = gr.Textbox(
                        label="Recent Logs",
                        lines=20,
                        max_lines=50,
                        interactive=False
                    )
                    refresh_logs_btn = gr.Button("🔄 Refresh Logs")
            
            # Event handlers
            refresh_status_btn.click(
                self._get_system_status,
                outputs=[system_status, last_run_info]
            )
            
            run_now_btn.click(
                self._run_pipeline,
                outputs=[run_output, recent_runs_df, last_run_info]
            )
            
            refresh_sources_btn.click(
                self._get_sources,
                outputs=[sources_df]
            )
            
            test_email_btn.click(
                self._test_email,
                inputs=[email_to],
                outputs=[test_email_result]
            )
            
            refresh_logs_btn.click(
                self._get_recent_logs,
                outputs=[logs_output]
            )
            
            # Load initial data
            app.load(
                self._get_system_status,
                outputs=[system_status, last_run_info]
            )
            
            app.load(
                self._get_sources,
                outputs=[sources_df]
            )
            
            app.load(
                self._get_recent_runs,
                outputs=[recent_runs_df]
            )
        
        self.app = app
    
    def _get_system_status(self) -> Tuple[str, str]:
        """Get current system status from API."""
        
        try:
            # Get health status from API
            health = self._api_request("GET", "/health")
            
            if "error" in health:
                return f"<div class='status-card status-unhealthy'><p>Error: {health['error']}</p></div>", ""
            
            components = health.get("components", {})
            db_healthy = components.get("database", {}).get("status") == "healthy"
            storage_healthy = components.get("storage", {}).get("status") == "healthy"
            email_configured = components.get("email", {}).get("status") == "configured"
            
            # Generate status HTML
            status_html = f"""
            <div class="status-card {'status-healthy' if health.get('status') == 'healthy' else 'status-unhealthy'}">
                <h3>System Health</h3>
                <ul>
                    <li>{'✅' if db_healthy else '❌'} Database: {components.get('database', {}).get('status', 'unknown')}</li>
                    <li>{'✅' if storage_healthy else '❌'} Storage: {components.get('storage', {}).get('status', 'unknown')}</li>
                    <li>{'✅' if email_configured else '❌'} Email: {components.get('email', {}).get('status', 'unknown')}</li>
                </ul>
                <p><small>Last checked: {datetime.now().strftime('%H:%M:%S')}</small></p>
            </div>
            """
            
            # Get last run info from API
            stats = self._api_request("GET", "/api/v1/runs/stats")
            
            if stats and not "error" in stats and stats.get("last_run"):
                last_run = stats["last_run"]
                status_icon = "✅" if last_run['status'] == 'completed' else "❌" if last_run['status'] == 'failed' else "🔄"
                last_run_html = f"""
                <div class="status-card">
                    <h3>Last Run</h3>
                    <p>{status_icon} <strong>{last_run['status'].title()}</strong></p>
                    <p>Started: {last_run['started_at'][:16] if last_run.get('started_at') else 'N/A'}</p>
                    <p>ID: {last_run['run_id'][:8]}...</p>
                </div>
                """
            else:
                last_run_html = """
                <div class="status-card">
                    <h3>Last Run</h3>
                    <p>No runs found</p>
                </div>
                """
            
            return status_html, last_run_html
        
        except Exception as e:
            logger.error("Failed to get system status", error=str(e))
            return f"<div class='status-card status-unhealthy'><p>Error: {e}</p></div>", ""
    
    def _run_pipeline(self) -> Tuple[str, List, str]:
        """Execute the pipeline via API."""
        
        try:
            # Trigger run via API
            result = self._api_request("POST", "/api/v1/runs/trigger", json={
                "triggered_by": "ui",
                "triggered_by_user": "admin",
                "send_email": True
            })
            
            if "error" in result:
                output_html = f"<div style='color: red;'>❌ Error: {result['error']}</div>"
                return output_html, [], ""
            
            run_id = result.get("run_id")
            
            # Poll for completion (simplified - in production use WebSocket)
            output_html = f"""
            <div style='color: blue;'>
                <h3>🚀 Pipeline Started</h3>
                <p>Run ID: {run_id}</p>
                <p>Status: Running...</p>
                <p><small>Check status in Recent Runs table</small></p>
            </div>
            """
            
            # Refresh other components
            recent_runs = self._get_recent_runs()
            _, last_run_info = self._get_system_status()
            
            return output_html, recent_runs, last_run_info
        
        except Exception as e:
            logger.error("Manual pipeline run failed", error=str(e))
            return f"<div style='color: red;'>❌ Error: {e}</div>", [], ""
    
    def _get_recent_runs(self) -> List:
        """Get recent pipeline runs from API."""
        
        try:
            result = self._api_request("GET", "/api/v1/runs", params={"page": 1, "page_size": 10})
            
            if "error" in result:
                return []
            
            runs = result.get("runs", [])
            
            table_data = []
            for run in runs:
                table_data.append([
                    run['run_id'][:8] + "...",
                    run['status'],
                    run['started_at'][:16] if run.get('started_at') else "N/A",
                    f"{run.get('duration_seconds', 0):.1f}s" if run.get('duration_seconds') else "N/A",
                    str(run.get('stats', {}).get('relevant_items', 0) if run.get('stats') else 0)
                ])
            
            return table_data
        
        except Exception as e:
            logger.error("Failed to get recent runs", error=str(e))
            return []
    
    def _get_sources(self) -> List:
        """Get active sources from API."""
        
        try:
            result = self._api_request("GET", "/api/v1/sources", params={"enabled_only": False})
            
            if "error" in result:
                return []
            
            sources = result.get("sources", [])
            
            table_data = []
            for source in sources:
                table_data.append([
                    source.get('name', 'N/A'),
                    source.get('parser', 'html'),
                    source.get('list_url', 'N/A')[:50] + "...",
                    source.get('rate_limit', '10/m'),
                    source.get('last_success_at', 'Never')[:16] if source.get('last_success_at') else 'Never'
                ])
            
            return table_data
        
        except Exception as e:
            logger.error("Failed to get sources", error=str(e))
            return []
    
    def _test_email(self, to_address: str) -> str:
        """Test email via API."""
        
        try:
            if not to_address or not to_address.strip():
                return "<div style='color: red;'>❌ Error: Please enter an email address</div>"
            
            result = self._api_request("POST", "/api/v1/admin/test-email", json={
                "to_address": to_address.strip()
            })
            
            if "error" in result:
                return f"<div style='color: red;'>❌ Error: {result['error']}</div>"
            
            if result.get("status") == "success":
                return f"<div style='color: green;'>✅ Test email sent successfully to {to_address}</div>"
            else:
                return "<div style='color: red;'>❌ Test email failed</div>"
        
        except Exception as e:
            return f"<div style='color: red;'>❌ Email test error: {e}</div>"
    
    def _get_recent_logs(self) -> str:
        """Get recent log entries."""
        
        try:
            # Read recent logs from file
            import os
            log_file = "logs/tenderai.log"
            
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    # Get last 100 lines
                    recent_lines = lines[-100:] if len(lines) > 100 else lines
                    return ''.join(recent_lines)
            else:
                return "No log file found"
        
        except Exception as e:
            return f"Error reading logs: {e}"
    
    def launch(self, **kwargs):
        """Launch the Gradio interface."""
        
        default_kwargs = {
            'server_name': '0.0.0.0',
            'server_port': 7860,
            'share': False,
            'debug': settings.debug,
            'auth': None  # TODO: Implement authentication
        }
        
        # Override with provided kwargs
        default_kwargs.update(kwargs)
        
        logger.info(
            "Starting Gradio UI",
            port=default_kwargs['server_port'],
            debug=default_kwargs['debug']
        )
        
        return self.app.launch(**default_kwargs)


def create_ui(api_url: Optional[str] = None) -> TenderAIUI:
    """Create and return the UI instance."""
    return TenderAIUI(api_url=api_url)


if __name__ == "__main__":
    # Run UI directly
    ui = create_ui()
    ui.launch()