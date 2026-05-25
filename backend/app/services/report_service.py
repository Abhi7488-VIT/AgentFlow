from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import io
from app.models.report import Report
from app.core.logging import get_logger

logger = get_logger(__name__)

async def get_report(db: AsyncSession, report_id) -> Report | None:
    result = await db.execute(select(Report).where(Report.id == report_id))
    return result.scalar_one_or_none()

async def list_reports(db: AsyncSession, user_id, skip: int = 0, limit: int = 100) -> tuple[list[Report], int]:
    result = await db.execute(
        select(Report)
        .where(Report.user_id == user_id)
        .order_by(Report.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    reports = list(result.scalars().all())
    
    count_result = await db.execute(select(func.count(Report.id)).where(Report.user_id == user_id))
    total = count_result.scalar()
    
    return reports, total

from sqlalchemy import delete
from app.models.workflow import Workflow

async def delete_report(db: AsyncSession, report_id) -> bool:
    report = await get_report(db, report_id)
    if not report:
        return False
        
    workflow_id = report.workflow_id
    
    # First delete the report to avoid foreign key constraints
    result = await db.execute(delete(Report).where(Report.id == report_id))
    
    # Then cascade delete the workflow if it existed
    if workflow_id:
        from app.models.scraped_data import ScrapedData
        from app.models.agent_log import AgentLog
        from app.models.analytics import Analytics
        from app.models.embedding_metadata import EmbeddingMetadata
        
        await db.execute(delete(EmbeddingMetadata).where(EmbeddingMetadata.workflow_id == workflow_id))
        await db.execute(delete(Analytics).where(Analytics.workflow_id == workflow_id))
        await db.execute(delete(AgentLog).where(AgentLog.workflow_id == workflow_id))
        await db.execute(delete(ScrapedData).where(ScrapedData.workflow_id == workflow_id))
        await db.execute(delete(Workflow).where(Workflow.id == workflow_id))
        
    await db.commit()
    return result.rowcount > 0

def generate_pdf(report: Report) -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib import colors
        
        buffer = io.BytesIO()
        # Add a little padding to the document
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
        
        styles = getSampleStyleSheet()
        
        # Custom vibrant styles
        custom_title = ParagraphStyle(
            name='CustomTitle',
            parent=styles['Heading1'],
            fontSize=22,
            spaceAfter=24,
            textColor=colors.HexColor('#4F46E5'), # Indigo
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        custom_heading = ParagraphStyle(
            name='CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor('#2563EB'), # Blue
            fontName='Helvetica-Bold',
            borderPadding=4
        )
        
        custom_normal = ParagraphStyle(
            name='CustomNormal',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=8,
            textColor=colors.HexColor('#1F2937'), # Dark Gray
            fontName='Helvetica',
            leading=16
        )
        
        custom_bullet = ParagraphStyle(
            name='CustomBullet',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=6,
            leftIndent=20,
            textColor=colors.HexColor('#374151'),
            fontName='Helvetica',
            leading=15,
            bulletIndent=10
        )
        
        flowables = []
        
        flowables.append(Paragraph(report.title or "Market Research Report", custom_title))
        
        flowables.append(Paragraph("Executive Summary", custom_heading))
        flowables.append(Paragraph(report.executive_summary or "No summary available.", custom_normal))
        
        # Load the dynamic advanced sections
        sections = {}
        try:
            if report.full_report:
                import json
                sections = json.loads(report.full_report)
        except Exception:
            pass
            
        # Dynamically render all sections
        for section_title, content in sections.items():
            flowables.append(Paragraph(section_title, custom_heading))
            
            if isinstance(content, list):
                for item in content:
                    flowables.append(Paragraph(f"<font color='#8B5CF6'>•</font> {item}", custom_bullet))
            elif isinstance(content, dict):
                for key, value in content.items():
                    if isinstance(value, list):
                        val_str = ', '.join(str(v) for v in value)
                        flowables.append(Paragraph(f"<b><font color='#4F46E5'>{key.replace('_', ' ').title()}:</font></b> {val_str}", custom_normal))
                    else:
                        flowables.append(Paragraph(f"<b><font color='#4F46E5'>{key.replace('_', ' ').title()}:</font></b> {value}", custom_normal))
            else:
                paragraphs = str(content).split('\n')
                for p in paragraphs:
                    if p.strip():
                        # Replace basic markdown bold with HTML bold for reportlab
                        formatted_p = p.strip().replace('**', '<b>').replace('**', '</b>')
                        # Note: replace with <b> requires alternating tags, a simpler way is regex or just stripping
                        # Let's just strip markdown asterisks for safety if it's too complex, or rely on simple replacement
                        # Actually, ReportLab supports <b>...</b>, but if we have **bold**, we'd need regex.
                        # For now, let's just use the string directly and remove markdown asterisks
                        clean_p = p.strip().replace('**', '')
                        flowables.append(Paragraph(clean_p, custom_normal))

        if not sections and report.recommendations:
            flowables.append(Paragraph("Recommendations", custom_heading))
            for rec in report.recommendations:
                flowables.append(Paragraph(f"<font color='#8B5CF6'>•</font> {rec}", custom_bullet))
            
        doc.build(flowables)
        buffer.seek(0)
        return buffer.read()
    except Exception as e:
        logger.error(f"Failed to generate PDF: {e}")
        return b"%PDF-1.4 Error generating PDF"

def generate_docx(report: Report) -> bytes:
    try:
        import docx
        doc = docx.Document()
        
        doc.add_heading(report.title or "Market Research Report", 0)
        
        doc.add_heading("Executive Summary", level=1)
        doc.add_paragraph(report.executive_summary or "No summary available.")
        
        doc.add_heading("Recommendations", level=1)
        for rec in (report.recommendations or []):
            doc.add_paragraph(rec, style='List Bullet')
            
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.read()
    except Exception as e:
        logger.error(f"Failed to generate DOCX: {e}")
        return b"Error generating DOCX"
