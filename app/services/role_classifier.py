"""Classify extracted job into role categories and compute fit score."""

import logging
import re

from app.core.config import Config
from app.models.job import ExtractedJob

logger = logging.getLogger(__name__)


def classify_role(job: ExtractedJob) -> tuple[str, float, str]:
    """Classify a job into a role category and compute fit score.

    Returns: (role_category, fit_score, selected_profile)
    """
    config = Config.get()
    matching = config.job_matching.get("matching", {})
    categories = matching.get("role_categories", [])
    profiles = config.application_profiles.get("profiles", {})

    text = f"{job.job_title} {job.description} {job.requirements}".lower()

    best_category = "default"
    best_score = 0.0
    best_match_count = 0

    for cat in categories:
        cat_name = cat.get("name", "")
        keywords = cat.get("keywords", [])
        match_count = 0
        for kw in keywords:
            if re.search(re.escape(kw.lower()), text):
                match_count += 1

        if not keywords:
            continue

        # Score based on keyword match ratio
        match_ratio = match_count / len(keywords)
        score = match_ratio * 100

        if score > best_score:
            best_score = score
            best_category = cat_name
            best_match_count = match_count

    # Select matching application profile
    selected_profile = best_category if best_category in profiles else "default"

    # Compute fit score using master CV skills overlap
    master_cv = config.master_cv.get("master_cv", {})
    skills = master_cv.get("skills", {})
    all_skills = []
    for skill_group in skills.values():
        if isinstance(skill_group, list):
            all_skills.extend([s.lower() for s in skill_group])

    skill_matches = sum(1 for s in all_skills if s and s in text)
    skill_bonus = min(30, skill_matches * 5)

    fit_score = min(100, best_score + skill_bonus)

    logger.info(
        f"Role classification: category={best_category}, "
        f"fit_score={fit_score:.1f}, profile={selected_profile}, "
        f"keyword_matches={best_match_count}, skill_matches={skill_matches}"
    )

    return best_category, fit_score, selected_profile
