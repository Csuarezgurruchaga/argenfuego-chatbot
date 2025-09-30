import os
import json
import base64
import time
import logging
from typing import List, Dict, Any, Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

logger = logging.getLogger(__name__)


SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.readonly'
]


class SheetsService:
    def __init__(self):
        self.enabled = os.getenv('ENABLE_SHEETS_METRICS', 'false').lower() == 'true'
        self.spreadsheet_metrics_id = os.getenv('SHEETS_METRICS_SPREADSHEET_ID', '').strip()
        self.spreadsheet_errors_id = os.getenv('SHEETS_ERRORS_SPREADSHEET_ID', '').strip() or self.spreadsheet_metrics_id
        # Backward compatibility
        default_metrics = os.getenv('SHEETS_METRICS_SHEET_NAME', 'METRICS_TECH').strip()
        self.business_sheet_name = os.getenv('SHEETS_BUSINESS_SHEET_NAME', 'METRICS_BUSINESS').strip()
        self.tech_sheet_name = os.getenv('SHEETS_TECH_SHEET_NAME', default_metrics).strip()
        self.errors_sheet_name = os.getenv('SHEETS_ERRORS_SHEET_NAME', 'ERRORS').strip()
        self.survey_sheet_name = os.getenv('SHEETS_SURVEY_SHEET_NAME', 'ENCUESTA_RESULTADOS').strip()
        self.kpi_sheet_name = os.getenv('SHEETS_KPI_SHEET_NAME', 'KPIs').strip()

        self._gc = None
        self._last_auth_ts = 0
        self._auth_ttl = 60 * 30  # 30 min

        if not self.enabled:
            logger.info('SheetsService disabled (ENABLE_SHEETS_METRICS=false)')
        elif not self.spreadsheet_metrics_id:
            logger.warning('SHEETS_METRICS_SPREADSHEET_ID not set - SheetsService disabled')
            self.enabled = False

    def _load_credentials(self):
        sa_raw = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
        if not sa_raw:
            raise ValueError('GOOGLE_SERVICE_ACCOUNT_JSON is required for SheetsService')
        try:
            # Support base64 or raw JSON
            if sa_raw.startswith('{'):
                info = json.loads(sa_raw)
            else:
                decoded = base64.b64decode(sa_raw)
                info = json.loads(decoded)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            return creds
        except Exception as e:
            raise ValueError(f'Invalid GOOGLE_SERVICE_ACCOUNT_JSON: {str(e)}')

    def _get_client(self):
        now = time.time()
        if self._gc and now - self._last_auth_ts < self._auth_ttl:
            return self._gc
        if gspread is None or Credentials is None:
            raise RuntimeError('gspread/google-auth not installed')
        creds = self._load_credentials()
        self._gc = gspread.authorize(creds)
        self._last_auth_ts = now
        return self._gc

    def append_row(self, target: str, row: List[Any]) -> bool:
        """
        target: 'business', 'tech', 'errors', 'survey', or 'kpis'
        row: list of values to append
        """
        if not self.enabled:
            return False
        try:
            gc = self._get_client()
            if target == 'errors':
                ss_id = self.spreadsheet_errors_id
                sheet_name = self.errors_sheet_name
            elif target == 'business':
                ss_id = self.spreadsheet_metrics_id
                sheet_name = self.business_sheet_name
            elif target == 'tech':
                ss_id = self.spreadsheet_metrics_id
                sheet_name = self.tech_sheet_name
            elif target == 'survey':
                ss_id = self.spreadsheet_metrics_id
                sheet_name = self.survey_sheet_name
            elif target == 'kpis':
                ss_id = self.spreadsheet_metrics_id
                sheet_name = self.kpi_sheet_name
            else:
                ss_id = self.spreadsheet_metrics_id
                sheet_name = self.tech_sheet_name

            sh = gc.open_by_key(ss_id)
            ws = sh.worksheet(sheet_name)
            ws.append_row(row, value_input_option='RAW')
            return True
        except Exception as e:
            logger.error(f'Sheets append_row error ({target}): {str(e)}')
            return False


sheets_service = SheetsService()


