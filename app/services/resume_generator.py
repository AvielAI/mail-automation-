"""Resume generation using Jinja2 templates and python-docx, with PDF conversion."""

import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.core.config import Config, GENERATED_DIR
from app.core.database import get_db
from app.models.job import ExtractedJob

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Remove or replace invalid filename characters."""
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:80]


def create_job_folder(job: ExtractedJob) -> Path:
    """Create a per-job output folder."""
    date_str = datetime.now().strftime("%Y%m%d")
    company = sanitize_filename(job.company or "Unknown")
    title = sanitize_filename(job.job_title or "Job")
    folder_name = f"{date_str}_{company}_{title}"
    folder = GENERATED_DIR / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def build_resume_docx(job: ExtractedJob, profile_name: str, output_path: Path) -> Path:
    """Build a tailored DOCX resume from source-of-truth YAML data only."""
    config = Config.get()
    candidate = config.candidate
    master_cv = config.master_cv.get("master_cv", {})
    profiles = config.application_profiles.get("profiles", {})
    profile = profiles.get(profile_name, profiles.get("default", {}))
    emphasis = profile.get("emphasis", [])

    doc = Document()

    # --- Styles ---
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # --- Header: Name & Contact ---
    header = doc.add_paragraph()
    header.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = header.add_run(candidate.get("full_name", ""))
    name_run.bold = True
    name_run.font.size = Pt(20)
    name_run.font.color.rgb = RGBColor(0x1A, 0x3C, 0x6E)

    contact_parts = []
    if candidate.get("email"):
        contact_parts.append(candidate["email"])
    if candidate.get("phone"):
        contact_parts.append(candidate["phone"])
    if candidate.get("location"):
        contact_parts.append(candidate["location"])
    if candidate.get("linkedin"):
        contact_parts.append(candidate["linkedin"])
    if candidate.get("github"):
        contact_parts.append(candidate["github"])

    contact = doc.add_paragraph()
    contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact_run = contact.add_run(" | ".join(contact_parts))
    contact_run.font.size = Pt(9)
    contact_run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    # --- Summary ---
    if candidate.get("summary"):
        doc.add_heading("Summary", level=2)
        doc.add_paragraph(candidate["summary"].strip())

    # --- Skills (if emphasized) ---
    skills = master_cv.get("skills", {})
    if "skills" in emphasis or "programming_languages" in emphasis or "frameworks" in emphasis:
        has_skills = any(
            isinstance(v, list) and len(v) > 0 for v in skills.values()
        )
        if has_skills:
            doc.add_heading("Skills", level=2)
            for category_key in emphasis:
                if category_key in skills and isinstance(skills[category_key], list) and skills[category_key]:
                    label = category_key.replace("_", " ").title()
                    p = doc.add_paragraph()
                    bold_run = p.add_run(f"{label}: ")
                    bold_run.bold = True
                    p.add_run(", ".join(skills[category_key]))

            # Add remaining skill categories not in emphasis
            for cat, items in skills.items():
                if cat not in emphasis and isinstance(items, list) and items:
                    label = cat.replace("_", " ").title()
                    p = doc.add_paragraph()
                    bold_run = p.add_run(f"{label}: ")
                    bold_run.bold = True
                    p.add_run(", ".join(items))

    # --- Experience ---
    experience = master_cv.get("experience", [])
    real_experience = [e for e in experience if e.get("company")]
    if real_experience and ("experience" in emphasis or not emphasis):
        doc.add_heading("Experience", level=2)
        for exp in real_experience:
            p = doc.add_paragraph()
            role_run = p.add_run(f"{exp.get('role', '')} — {exp.get('company', '')}")
            role_run.bold = True
            dates = f"{exp.get('start_date', '')} – {exp.get('end_date', 'Present')}"
            if exp.get("location"):
                dates += f" | {exp['location']}"
            doc.add_paragraph(dates).runs[0].font.size = Pt(9)

            if exp.get("description"):
                doc.add_paragraph(exp["description"])

            if exp.get("achievements"):
                for ach in exp["achievements"]:
                    doc.add_paragraph(ach, style="List Bullet")

            if exp.get("technologies"):
                tech_p = doc.add_paragraph()
                tech_run = tech_p.add_run("Technologies: ")
                tech_run.bold = True
                tech_p.add_run(", ".join(exp["technologies"]))

    # --- Projects ---
    projects = master_cv.get("projects", [])
    real_projects = [p for p in projects if p.get("name")]
    if real_projects and ("projects" in emphasis or not emphasis):
        doc.add_heading("Projects", level=2)
        for proj in real_projects:
            p = doc.add_paragraph()
            proj_run = p.add_run(proj.get("name", ""))
            proj_run.bold = True
            if proj.get("url"):
                p.add_run(f"  ({proj['url']})")
            if proj.get("description"):
                doc.add_paragraph(proj["description"])
            if proj.get("technologies"):
                tech_p = doc.add_paragraph()
                tech_run = tech_p.add_run("Technologies: ")
                tech_run.bold = True
                tech_p.add_run(", ".join(proj["technologies"]))
            if proj.get("highlights"):
                for h in proj["highlights"]:
                    doc.add_paragraph(h, style="List Bullet")

    # --- Education ---
    education = candidate.get("education", [])
    real_education = [e for e in education if e.get("institution")]
    if real_education:
        doc.add_heading("Education", level=2)
        for edu in real_education:
            p = doc.add_paragraph()
            edu_run = p.add_run(
                f"{edu.get('degree', '')} in {edu.get('field', '')} — {edu.get('institution', '')}"
            )
            edu_run.bold = True
            dates = f"{edu.get('start_date', '')} – {edu.get('end_date', '')}"
            if edu.get("gpa"):
                dates += f" | GPA: {edu['gpa']}"
            doc.add_paragraph(dates).runs[0].font.size = Pt(9)

    # --- Languages ---
    languages = candidate.get("languages", [])
    if languages:
        doc.add_heading("Languages", level=2)
        lang_text = ", ".join(
            f"{l.get('language', '')} ({l.get('level', '')})" for l in languages if l.get("language")
        )
        doc.add_paragraph(lang_text)

    # --- Military Service ---
    military = candidate.get("military_service", {})
    if military and military.get("role"):
        doc.add_heading("Military Service", level=2)
        p = doc.add_paragraph()
        mil_run = p.add_run(f"{military.get('role', '')} — {military.get('unit', '')}")
        mil_run.bold = True
        dates = f"{military.get('start_date', '')} – {military.get('end_date', '')}"
        doc.add_paragraph(dates).runs[0].font.size = Pt(9)
        if military.get("description"):
            doc.add_paragraph(military["description"])

    # --- Certifications ---
    certs = master_cv.get("certifications", [])
    if certs and any(c for c in certs if c):
        doc.add_heading("Certifications", level=2)
        for cert in certs:
            if cert:
                doc.add_paragraph(cert, style="List Bullet")

    # Save
    doc.save(str(output_path))
    logger.info(f"Resume DOCX saved: {output_path}")
    return output_path


def convert_to_pdf(docx_path: Path) -> Path | None:
    """Convert DOCX to PDF using LibreOffice headless."""
    pdf_path = docx_path.with_suffix(".pdf")
    try:
        result = subprocess.run(
            [
                "libreoffice", "--headless", "--convert-to", "pdf",
                "--outdir", str(docx_path.parent),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and pdf_path.exists():
            logger.info(f"PDF generated: {pdf_path}")
            return pdf_path
        else:
            logger.warning(f"LibreOffice conversion failed: {result.stderr}")
    except FileNotFoundError:
        logger.warning("LibreOffice not found. PDF conversion skipped.")
    except subprocess.TimeoutExpired:
        logger.warning("LibreOffice conversion timed out.")
    return None


def generate_resume(job: ExtractedJob, profile_name: str, job_id: int | None = None) -> dict:
    """Generate resume DOCX and PDF for a job.

    Returns dict with paths: {'docx': path, 'pdf': path, 'folder': path}
    """
    folder = create_job_folder(job)
    config = Config.get()
    candidate = config.candidate

    name = sanitize_filename(candidate.get("full_name", "Resume"))
    title = sanitize_filename(job.job_title or "Job")
    date_str = datetime.now().strftime("%Y%m%d")
    base_name = f"{name}_{title}_{date_str}"

    docx_path = folder / f"{base_name}.docx"
    build_resume_docx(job, profile_name, docx_path)

    pdf_path = convert_to_pdf(docx_path)

    # Store in DB
    if job_id:
        with get_db() as db:
            db.execute(
                "UPDATE jobs SET generated_resume_docx = ?, generated_resume_pdf = ? WHERE id = ?",
                (str(docx_path), str(pdf_path) if pdf_path else "", job_id),
            )
            for fmt, path in [("docx", docx_path), ("pdf", pdf_path)]:
                if path:
                    db.execute(
                        "INSERT INTO generated_files (job_id, file_type, file_format, file_path) VALUES (?, ?, ?, ?)",
                        (job_id, "resume", fmt, str(path)),
                    )

    return {
        "docx": str(docx_path),
        "pdf": str(pdf_path) if pdf_path else None,
        "folder": str(folder),
    }
