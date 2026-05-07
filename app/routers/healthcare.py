"""
Healthcare router — full healthcare system with appointments, MyChart,
medications, conditions, referrals, lab results, and vaccinations.

Endpoints:
  GET   /healthcare/profile                — get/create care profile
  POST  /healthcare/profile                — update care profile
  GET   /healthcare/doctors                — list NPC doctors (filtered by specialty)
  GET   /healthcare/insurance-plans        — list available insurance plans
  POST  /healthcare/insurance              — change insurance plan

  POST  /healthcare/appointments/schedule  — schedule a new appointment
  GET   /healthcare/appointments           — list appointments (upcoming + past)
  POST  /healthcare/appointments/{id}/complete — mark appointment complete
  POST  /healthcare/appointments/{id}/cancel   — cancel appointment
  GET   /healthcare/appointments/{id}      — get single appointment with follow-ups

  GET   /healthcare/medications            — list active medications
  POST  /healthcare/medications/{id}/deactivate — stop a medication

  GET   /healthcare/conditions             — list conditions
  GET   /healthcare/referrals              — list pending referrals
  GET   /healthcare/lab-results            — list lab results
  GET   /healthcare/vaccinations           — list vaccinations
  POST  /healthcare/vaccinations/add       — log a vaccination
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import date, datetime, timedelta
import json
import random

from app.database import get_db, is_postgres
from app.services.notifications import push_notification

router = APIRouter(prefix="/healthcare", tags=["healthcare"])


# ── NPC Doctor Roster ─────────────────────────────────────────────────────────

DOCTORS = {
    "dr_reyes": {
        "id": "dr_reyes", "name": "Dr. Valentina Reyes",
        "pronouns": "she/her", "specialty": "primary_care",
        "specialties": ["primary_care", "general"],
        "bio": "Warm and thorough — never rushes you. Known for remembering every patient's story. Specialises in preventive care.",
        "emoji": "👩‍⚕️",
    },
    "dr_ellwood": {
        "id": "dr_ellwood", "name": "Dr. Marcus Ellwood",
        "pronouns": "he/him", "specialty": "primary_care",
        "specialties": ["primary_care", "general", "urgent_care"],
        "bio": "Dry sense of humour, extremely competent. Goes straight to the point. Patients appreciate his directness.",
        "emoji": "👨‍⚕️",
    },
    "dr_okafor": {
        "id": "dr_okafor", "name": "Dr. Sable Okafor",
        "pronouns": "she/her", "specialty": "obgyn",
        "specialties": ["obgyn", "reproductive", "pregnancy", "ivf"],
        "bio": "Gentle and deeply compassionate. Specialises in high-risk pregnancy and IVF support. Makes patients feel safe during vulnerable appointments.",
        "emoji": "👩‍⚕️",
    },
    "dr_anand": {
        "id": "dr_anand", "name": "Dr. Priya Anand",
        "pronouns": "she/her", "specialty": "obgyn",
        "specialties": ["obgyn", "reproductive", "fertility", "ivf"],
        "bio": "Energetic, modern approach. Champions patient autonomy. Strong advocate for reproductive rights and fertility preservation.",
        "emoji": "👩‍⚕️",
    },
    "dr_marchetti": {
        "id": "dr_marchetti", "name": "Dr. Theo Marchetti",
        "pronouns": "he/him", "specialty": "mental_health",
        "specialties": ["mental_health", "psychiatry", "therapy"],
        "bio": "Quietly perceptive. Trained in trauma-informed care and EMDR. Creates a space where patients feel genuinely heard.",
        "emoji": "🧠",
    },
    "dr_fontaine": {
        "id": "dr_fontaine", "name": "Dr. Celia Fontaine",
        "pronouns": "she/her", "specialty": "mental_health",
        "specialties": ["mental_health", "therapy", "grief", "relationship"],
        "bio": "Specialises in relationship dynamics, grief, and identity. Known for gentle but honest feedback that patients carry with them for years.",
        "emoji": "🧠",
    },
    "dr_nakashima": {
        "id": "dr_nakashima", "name": "Dr. Remi Nakashima",
        "pronouns": "they/them", "specialty": "dental",
        "specialties": ["dental"],
        "bio": "Precise and patient with anxious visitors. Specialises in restorative and cosmetic dentistry. Plays soft music in their practice.",
        "emoji": "🦷",
    },
    "dr_haddad": {
        "id": "dr_haddad", "name": "Dr. Omar Haddad",
        "pronouns": "he/him", "specialty": "vision",
        "specialties": ["vision", "ophthalmology"],
        "bio": "Meticulous and detail-oriented. Specialises in medical eye conditions. Patients consistently feel informed and confident after appointments.",
        "emoji": "👁️",
    },
    "dr_stein": {
        "id": "dr_stein", "name": "Dr. Liora Stein",
        "pronouns": "she/her", "specialty": "dermatology",
        "specialties": ["dermatology"],
        "bio": "Calm and knowledgeable about both medical and cosmetic dermatology. Treats every concern as valid.",
        "emoji": "🫧",
    },
    "dr_parish": {
        "id": "dr_parish", "name": "Dr. Callum Parish",
        "pronouns": "he/him", "specialty": "cardiology",
        "specialties": ["cardiology"],
        "bio": "Reassuring presence. Experienced in preventive cardiology and complex heart conditions. Runners and athletes seek him out.",
        "emoji": "❤️",
    },
    "dr_tanaka": {
        "id": "dr_tanaka", "name": "Dr. Yuki Tanaka",
        "pronouns": "she/her", "specialty": "neurology",
        "specialties": ["neurology"],
        "bio": "Methodical and patient with complex cases. Specialises in migraine, sleep disorders, and cognitive health.",
        "emoji": "🧬",
    },
    "dr_patel": {
        "id": "dr_patel", "name": "Dr. Asha Patel",
        "pronouns": "she/her", "specialty": "endocrinology",
        "specialties": ["endocrinology"],
        "bio": "Holistic approach to hormonal health. Specialises in thyroid conditions, PCOS, and diabetes management.",
        "emoji": "⚗️",
    },
    "dr_calloway": {
        "id": "dr_calloway", "name": "Dr. Finn Calloway",
        "pronouns": "he/him", "specialty": "orthopedics",
        "specialties": ["orthopedics", "physical_therapy", "sports_medicine"],
        "bio": "Former athlete. Specialises in sports injuries, joint reconstruction, and return-to-movement rehabilitation.",
        "emoji": "🦴",
    },
    "dr_moreau": {
        "id": "dr_moreau", "name": "Dr. Celeste Moreau",
        "pronouns": "she/her", "specialty": "allergy",
        "specialties": ["allergy", "immunology"],
        "bio": "Precise and methodical. Patients appreciate her clear explanations and thorough testing protocols.",
        "emoji": "🌿",
    },
    "dr_rivera": {
        "id": "dr_rivera", "name": "Dr. Dante Rivera",
        "pronouns": "he/him", "specialty": "gastroenterology",
        "specialties": ["gastroenterology"],
        "bio": "Easy to talk to about difficult topics. Specialises in IBD, IBS, and digestive wellness. Non-judgmental approach.",
        "emoji": "🫁",
    },
    "dr_solberg": {
        "id": "dr_solberg", "name": "Dr. Ingrid Solberg",
        "pronouns": "she/her", "specialty": "urgent_care",
        "specialties": ["urgent_care", "emergency", "general"],
        "bio": "Unflappable under pressure. The doctor you want in a crisis. Efficient, decisive, and surprisingly warm given the pace of her work.",
        "emoji": "🚑",
    },
}

# Specialty → doctor IDs mapping for filtering
SPECIALTY_DOCTORS = {
    "primary_care":     ["dr_reyes", "dr_ellwood"],
    "general":          ["dr_reyes", "dr_ellwood", "dr_solberg"],
    "obgyn":            ["dr_okafor", "dr_anand"],
    "reproductive":     ["dr_okafor", "dr_anand"],
    "pregnancy":        ["dr_okafor", "dr_anand"],
    "ivf":              ["dr_okafor", "dr_anand"],
    "fertility":        ["dr_okafor", "dr_anand"],
    "mental_health":    ["dr_marchetti", "dr_fontaine"],
    "psychiatry":       ["dr_marchetti"],
    "therapy":          ["dr_fontaine", "dr_marchetti"],
    "grief":            ["dr_fontaine"],
    "relationship":     ["dr_fontaine"],
    "dental":           ["dr_nakashima"],
    "vision":           ["dr_haddad"],
    "ophthalmology":    ["dr_haddad"],
    "dermatology":      ["dr_stein"],
    "cardiology":       ["dr_parish"],
    "neurology":        ["dr_tanaka"],
    "endocrinology":    ["dr_patel"],
    "orthopedics":      ["dr_calloway"],
    "physical_therapy": ["dr_calloway"],
    "sports_medicine":  ["dr_calloway"],
    "allergy":          ["dr_moreau"],
    "immunology":       ["dr_moreau"],
    "gastroenterology": ["dr_rivera"],
    "urgent_care":      ["dr_solberg", "dr_ellwood"],
    "emergency":        ["dr_solberg"],
}

# ── Insurance Plans ───────────────────────────────────────────────────────────

INSURANCE_PLANS = {
    "uninsured": {
        "id": "uninsured", "name": "Uninsured",
        "description": "Full out-of-pocket costs. No specialist coverage. Some clinics offer sliding scale.",
        "monthly_premium": 0,
        "copay_primary": 45, "copay_specialist": 120, "copay_urgent": 150,
        "copay_mental_health": 80, "copay_dental": 90, "copay_vision": 60,
        "covers_ivf": False, "covers_dental": False, "covers_vision": False,
        "haul_discount": 0, "color": "#9e9e9e",
    },
    "luminos_public": {
        "id": "luminos_public", "name": "Luminos Public Health",
        "description": "Government-sponsored. Free or very low copay for primary care and mental health. Dental and vision not included.",
        "monthly_premium": 0,
        "copay_primary": 5, "copay_specialist": 30, "copay_urgent": 15,
        "copay_mental_health": 10, "copay_dental": 80, "copay_vision": 55,
        "covers_ivf": False, "covers_dental": False, "covers_vision": False,
        "haul_discount": 0, "color": "#4caf7d",
    },
    "clarity_basic": {
        "id": "clarity_basic", "name": "ClarityPlan Basic",
        "description": "Entry-level private insurance. Low premium, reduced copays. One specialist per quarter. Basic dental included.",
        "monthly_premium": 25,
        "copay_primary": 20, "copay_specialist": 60, "copay_urgent": 40,
        "copay_mental_health": 35, "copay_dental": 15, "copay_vision": 45,
        "covers_ivf": False, "covers_dental": True, "covers_vision": False,
        "haul_discount": 5, "color": "#5b9bd5",
    },
    "clarity_plus": {
        "id": "clarity_plus", "name": "ClarityPlan Plus",
        "description": "Mid-tier private. Lower copays across all specialties. Full dental, basic vision, mental health included.",
        "monthly_premium": 60,
        "copay_primary": 10, "copay_specialist": 30, "copay_urgent": 25,
        "copay_mental_health": 15, "copay_dental": 0, "copay_vision": 20,
        "covers_ivf": True, "covers_dental": True, "covers_vision": True,
        "haul_discount": 10, "color": "#7c5cbf",
    },
    "luminos_prestige": {
        "id": "luminos_prestige", "name": "Luminos Prestige",
        "description": "Premium coverage. Near-zero copays. Full specialty, dental, and vision. IVF partially covered. Priority scheduling.",
        "monthly_premium": 120,
        "copay_primary": 0, "copay_specialist": 10, "copay_urgent": 10,
        "copay_mental_health": 0, "copay_dental": 0, "copay_vision": 0,
        "covers_ivf": True, "covers_dental": True, "covers_vision": True,
        "haul_discount": 20, "color": "#c9a227",
    },
}

# ── Appointment types catalog ─────────────────────────────────────────────────

APPOINTMENT_TYPES = {
    "primary_care": {
        "label": "Primary Care", "emoji": "🏥",
        "specialties": [
            "Annual physical / wellness exam", "Sick visit", "Follow-up visit",
            "Telehealth / virtual visit", "Vaccination / immunization",
            "Lab work / bloodwork", "Prescription refill consultation",
        ],
        "copay_category": "primary", "doctors": ["dr_reyes", "dr_ellwood"],
    },
    "obgyn": {
        "label": "OB/GYN & Reproductive", "emoji": "🌸",
        "specialties": [
            "Annual exam / pap smear", "Prenatal visit — first trimester",
            "Prenatal visit — second trimester", "Prenatal visit — third trimester",
            "Postpartum checkup", "Fertility consultation",
            "IVF consultation", "IVF monitoring / ultrasound",
            "IVF egg retrieval", "IVF embryo transfer", "IVF beta test",
            "Surrogacy screening / clearance", "Miscarriage / pregnancy loss support",
            "Birth control consultation", "Menopause management",
        ],
        "copay_category": "specialist", "doctors": ["dr_okafor", "dr_anand"],
    },
    "mental_health": {
        "label": "Mental Health", "emoji": "🧠",
        "specialties": [
            "Individual therapy", "Couples / relationship therapy",
            "Group therapy", "Psychiatry evaluation", "Medication management",
            "Crisis counseling", "Grief counseling",
            "Trauma-focused therapy (EMDR)", "Addiction counseling",
            "Sleep disorder consultation",
        ],
        "copay_category": "mental_health", "doctors": ["dr_marchetti", "dr_fontaine"],
    },
    "dental": {
        "label": "Dental", "emoji": "🦷",
        "specialties": [
            "Routine cleaning / checkup", "X-rays", "Filling",
            "Root canal", "Extraction", "Crown / bridge",
            "Orthodontic adjustment", "Teeth whitening consultation",
            "Emergency dental visit",
        ],
        "copay_category": "dental", "doctors": ["dr_nakashima"],
    },
    "vision": {
        "label": "Vision", "emoji": "👁️",
        "specialties": [
            "Routine eye exam", "Contact lens fitting / follow-up",
            "Glasses prescription", "Ophthalmology / medical eye care",
            "Laser vision consultation", "Emergency vision visit",
        ],
        "copay_category": "vision", "doctors": ["dr_haddad"],
    },
    "dermatology": {
        "label": "Dermatology", "emoji": "🫧",
        "specialties": [
            "Routine skin check", "Acne / condition treatment",
            "Mole removal / biopsy", "Cosmetic dermatology consultation",
            "Eczema / psoriasis management",
        ],
        "copay_category": "specialist", "doctors": ["dr_stein"],
    },
    "cardiology": {
        "label": "Cardiology", "emoji": "❤️",
        "specialties": [
            "Routine cardiac checkup", "EKG / ECG", "Stress test",
            "Echocardiogram", "Hypertension management",
        ],
        "copay_category": "specialist", "doctors": ["dr_parish"],
    },
    "neurology": {
        "label": "Neurology", "emoji": "🧬",
        "specialties": [
            "Migraine consultation / management", "Epilepsy / seizure management",
            "Memory / cognitive evaluation", "Sleep study referral",
            "Nerve conduction study",
        ],
        "copay_category": "specialist", "doctors": ["dr_tanaka"],
    },
    "orthopedics": {
        "label": "Orthopedics & Physical Therapy", "emoji": "🦴",
        "specialties": [
            "Sports injury evaluation", "Joint pain consultation",
            "Post-surgery rehabilitation", "Physical therapy session",
            "Occupational therapy", "Chiropractic / spinal adjustment",
            "Bone density scan",
        ],
        "copay_category": "specialist", "doctors": ["dr_calloway"],
    },
    "endocrinology": {
        "label": "Endocrinology", "emoji": "⚗️",
        "specialties": [
            "Diabetes management", "Thyroid evaluation",
            "Hormonal imbalance consultation", "Weight management consultation",
            "Adrenal / metabolic workup",
        ],
        "copay_category": "specialist", "doctors": ["dr_patel"],
    },
    "allergy": {
        "label": "Allergy & Immunology", "emoji": "🌿",
        "specialties": [
            "Allergy testing", "Allergy shot / immunotherapy",
            "Asthma management", "Food allergy consultation",
        ],
        "copay_category": "specialist", "doctors": ["dr_moreau"],
    },
    "gastroenterology": {
        "label": "Gastroenterology", "emoji": "🫁",
        "specialties": [
            "Digestive health consultation", "Colonoscopy", "Endoscopy",
            "IBS / IBD management", "Acid reflux / GERD treatment",
        ],
        "copay_category": "specialist", "doctors": ["dr_rivera"],
    },
    "urgent_care": {
        "label": "Urgent & Emergency", "emoji": "🚑",
        "specialties": [
            "Urgent care visit", "Emergency room visit",
            "Ambulatory surgery / procedure",
            "Imaging — X-ray, MRI, CT scan, ultrasound",
        ],
        "copay_category": "urgent", "doctors": ["dr_solberg", "dr_ellwood"],
    },
    "specialist_other": {
        "label": "Specialist / Other", "emoji": "🔬",
        "specialties": [
            "Oncology consultation", "Rheumatology", "Pulmonology / respiratory",
            "Urology", "Hematology", "Nephrology / kidney",
            "Infectious disease", "Nutrition / dietitian",
            "Audiology / hearing", "Speech therapy",
            "Podiatry / foot care", "Plastic / reconstructive surgery consultation",
        ],
        "copay_category": "specialist", "doctors": ["dr_reyes", "dr_ellwood"],
    },
}


# ── Automated follow-up profiles ──────────────────────────────────────────────

def _get_followup_profile(appointment_type: str, specialty: str, concerns: str) -> dict:
    """
    Returns automated follow-up data based on appointment type and specialty.
    Each profile has: vibe, need_effects, prescription, diagnosis, referral, lab_result.
    All fields are optional — None means don't issue that follow-up.
    """
    concerns_lower = (concerns or "").lower()
    today = date.today().isoformat()

    profiles = {
        # ── Primary Care ──────────────────────────────────────────────────────
        "Annual physical / wellness exam": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -5, "recovery": 3},
            "summary": "Annual wellness exam completed. All routine screenings performed. Continue healthy habits.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Annual wellness — no acute concerns",
                "severity": "mild", "status": "resolved",
                "treatment_plan": "Continue routine preventive care. Follow up in 12 months.",
                "follow_up_recommended": 1, "follow_up_weeks": 52,
            },
            "referral": None,
            "lab_result": {
                "test_name": "Comprehensive Metabolic Panel",
                "result_value": "Within normal limits", "unit": "",
                "reference_range": "Standard ranges", "status": "normal",
            },
        },
        "Sick visit": {
            "vibe": "recovery_mode",
            "need_effects": {"stress": -3, "recovery": -5},
            "summary": "Sick visit completed. Treatment plan issued based on presenting symptoms.",
            "prescription": _sick_prescription(concerns_lower),
            "diagnosis": _sick_diagnosis(concerns_lower, today),
            "referral": None,
            "lab_result": None,
        },
        "Follow-up visit": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -5},
            "summary": "Follow-up visit completed. Condition progress reviewed.",
            "prescription": None, "diagnosis": None, "referral": None, "lab_result": None,
        },
        "Lab work / bloodwork": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -2},
            "summary": "Lab work completed. Results will be reviewed by your provider.",
            "prescription": None, "diagnosis": None, "referral": None,
            "lab_result": {
                "test_name": "Complete Blood Count (CBC)",
                "result_value": "Within normal limits", "unit": "",
                "reference_range": "Standard ranges", "status": "normal",
            },
        },
        "Vaccination / immunization": {
            "vibe": "preventive_care",
            "need_effects": {"stress": -2},
            "summary": "Vaccination administered. Mild soreness at injection site is normal.",
            "prescription": None, "diagnosis": None, "referral": None, "lab_result": None,
        },

        # ── OB/GYN ───────────────────────────────────────────────────────────
        "Annual exam / pap smear": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -5},
            "summary": "Annual gynecological exam and pap smear completed. Results pending.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Annual GYN exam — routine",
                "severity": "mild", "status": "resolved",
                "treatment_plan": "Routine annual exam. Follow up in 12 months or sooner if concerns arise.",
                "follow_up_recommended": 1, "follow_up_weeks": 52,
            },
            "referral": None,
            "lab_result": {
                "test_name": "Pap Smear", "result_value": "Normal",
                "unit": "", "reference_range": "Negative for intraepithelial lesion or malignancy",
                "status": "normal",
            },
        },
        "Prenatal visit — first trimester": {
            "vibe": "prenatal_glow",
            "need_effects": {"recovery": 5, "stress": -8},
            "summary": "First trimester prenatal visit completed. Baby is developing on track. All routine screenings ordered.",
            "prescription": {
                "name": "Prenatal Vitamins", "dosage": "1 tablet",
                "frequency": "Once daily", "prescribed_for": "Pregnancy nutritional support",
                "duration_days": None, "notes": "Take with food. Continue through pregnancy and breastfeeding if applicable.",
            },
            "diagnosis": {
                "condition_name": "First trimester pregnancy — routine",
                "severity": "mild", "status": "active",
                "treatment_plan": "Continue prenatal care. Next visit in 4 weeks.",
                "follow_up_recommended": 1, "follow_up_weeks": 4,
            },
            "referral": None,
            "lab_result": {
                "test_name": "First Trimester Bloodwork Panel",
                "result_value": "Normal pregnancy hormones", "unit": "",
                "reference_range": "hCG and progesterone within expected range",
                "status": "normal",
            },
        },
        "Prenatal visit — second trimester": {
            "vibe": "prenatal_glow",
            "need_effects": {"recovery": 5, "stress": -5},
            "summary": "Second trimester prenatal visit completed. Anatomy scan ordered.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Second trimester pregnancy — routine",
                "severity": "mild", "status": "active",
                "treatment_plan": "Routine prenatal monitoring. Next visit in 4 weeks.",
                "follow_up_recommended": 1, "follow_up_weeks": 4,
            },
            "referral": None, "lab_result": None,
        },
        "Prenatal visit — third trimester": {
            "vibe": "prenatal_glow",
            "need_effects": {"recovery": 3, "stress": -5},
            "summary": "Third trimester prenatal visit completed. Birth plan discussed.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Third trimester pregnancy — routine",
                "severity": "mild", "status": "active",
                "treatment_plan": "Weekly monitoring begins at 36 weeks. Birth plan on file.",
                "follow_up_recommended": 1, "follow_up_weeks": 2,
            },
            "referral": None, "lab_result": None,
        },
        "Postpartum checkup": {
            "vibe": "health_checked_in",
            "need_effects": {"recovery": 8, "stress": -10},
            "summary": "Postpartum checkup completed. Recovery assessed. Mental health screening performed.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Postpartum recovery — standard",
                "severity": "mild", "status": "active",
                "treatment_plan": "Continue rest and recovery. Seek support if experiencing mood changes. Follow up in 6 weeks.",
                "follow_up_recommended": 1, "follow_up_weeks": 6,
            },
            "referral": None, "lab_result": None,
        },
        "Fertility consultation": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -5},
            "summary": "Fertility consultation completed. Assessment performed and options discussed.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Fertility evaluation — initial consultation",
                "severity": "mild", "status": "monitoring",
                "treatment_plan": "Fertility workup initiated. Follow-up to review results and discuss next steps.",
                "follow_up_recommended": 1, "follow_up_weeks": 3,
            },
            "referral": None,
            "lab_result": {
                "test_name": "Fertility Panel — AMH, FSH, LH",
                "result_value": "Results pending", "unit": "",
                "reference_range": "Age-appropriate ranges", "status": "pending",
            },
        },
        "IVF consultation": {
            "vibe": "ivf_hopeful",
            "need_effects": {"stress": -5},
            "summary": "IVF consultation completed. Protocol reviewed and timeline established.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "IVF treatment initiated",
                "severity": "mild", "status": "active",
                "treatment_plan": "IVF protocol established. Begin monitoring cycle as scheduled.",
                "follow_up_recommended": 1, "follow_up_weeks": 2,
            },
            "referral": None, "lab_result": None,
            "ivf_stage_advance": "preparing",
        },
        "IVF monitoring / ultrasound": {
            "vibe": "ivf_hopeful",
            "need_effects": {"stress": -3},
            "summary": "IVF monitoring completed. Follicle development assessed.",
            "prescription": {
                "name": "Progesterone Support", "dosage": "As prescribed",
                "frequency": "As directed", "prescribed_for": "IVF cycle support",
                "duration_days": 14, "notes": "Continue as directed by your care team.",
            },
            "diagnosis": None, "referral": None, "lab_result": None,
            "ivf_stage_advance": "stimulation",
        },
        "IVF egg retrieval": {
            "vibe": "ivf_exhausted",
            "need_effects": {"recovery": -10, "stress": -5},
            "summary": "Egg retrieval completed. You may experience mild cramping and bloating. Rest today.",
            "prescription": {
                "name": "Post-Retrieval Pain Management", "dosage": "As prescribed",
                "frequency": "As needed for discomfort", "prescribed_for": "Post IVF retrieval recovery",
                "duration_days": 5, "notes": "Avoid strenuous activity for 48 hours. Contact clinic if pain is severe.",
            },
            "diagnosis": None, "referral": None, "lab_result": None,
            "ivf_stage_advance": "retrieval",
        },
        "IVF embryo transfer": {
            "vibe": "ivf_hopeful",
            "need_effects": {"stress": -5},
            "summary": "Embryo transfer completed. Rest today. The two week wait begins now.",
            "prescription": {
                "name": "Progesterone Supplementation", "dosage": "As prescribed",
                "frequency": "As directed", "prescribed_for": "Post-transfer embryo support",
                "duration_days": 14, "notes": "Critical — do not skip doses. Light activity is fine.",
            },
            "diagnosis": None, "referral": None, "lab_result": None,
            "ivf_stage_advance": "transfer",
        },
        "IVF beta test": {
            "vibe": "ivf_anxious",
            "need_effects": {"stress": -10},
            "summary": "Beta hCG blood test completed. Your provider will review results with you.",
            "prescription": None, "diagnosis": None, "referral": None,
            "lab_result": {
                "test_name": "Beta hCG — Pregnancy Test",
                "result_value": "Positive", "unit": "mIU/mL",
                "reference_range": "> 25 mIU/mL indicates pregnancy",
                "status": "normal",
            },
            "ivf_stage_advance": "beta_wait",
        },

        # ── Mental Health ─────────────────────────────────────────────────────
        "Individual therapy": {
            "vibe": "post_therapy",
            "need_effects": {"stress": -15, "fun": 5},
            "summary": "Therapy session completed. Good progress made. Continue reflecting on themes discussed.",
            "prescription": None, "diagnosis": None, "referral": None, "lab_result": None,
        },
        "Couples / relationship therapy": {
            "vibe": "post_therapy",
            "need_effects": {"stress": -10, "social": 5},
            "summary": "Couples therapy session completed. Communication strategies reviewed.",
            "prescription": None, "diagnosis": None, "referral": None, "lab_result": None,
        },
        "Psychiatry evaluation": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -8},
            "summary": "Psychiatric evaluation completed. Assessment and treatment plan established.",
            "prescription": {
                "name": "Medication as evaluated", "dosage": "As prescribed",
                "frequency": "As directed", "prescribed_for": "Mental health management",
                "duration_days": 30, "notes": "Follow up in 4 weeks to assess response. Contact provider with concerns.",
            },
            "diagnosis": {
                "condition_name": "Mental health condition — under psychiatric care",
                "severity": "moderate", "status": "managed",
                "treatment_plan": "Medication management initiated. Therapy recommended as adjunct treatment.",
                "follow_up_recommended": 1, "follow_up_weeks": 4,
            },
            "referral": None, "lab_result": None,
        },
        "Grief counseling": {
            "vibe": "post_therapy",
            "need_effects": {"stress": -12, "purpose": 5},
            "summary": "Grief counseling session completed. Grief is not linear — you are doing the work.",
            "prescription": None, "diagnosis": None, "referral": None, "lab_result": None,
        },

        # ── Dental ────────────────────────────────────────────────────────────
        "Routine cleaning / checkup": {
            "vibe": "fresh_smile",
            "need_effects": {"stress": -3},
            "summary": "Routine cleaning completed. Teeth and gums in good health. Keep up with flossing.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Dental checkup — no cavities",
                "severity": "mild", "status": "resolved",
                "treatment_plan": "Continue brushing twice daily and flossing. Next cleaning in 6 months.",
                "follow_up_recommended": 1, "follow_up_weeks": 26,
            },
            "referral": None, "lab_result": None,
        },
        "Emergency dental visit": {
            "vibe": "recovery_mode",
            "need_effects": {"stress": -5, "recovery": -5},
            "summary": "Emergency dental treatment completed. Follow post-procedure care instructions carefully.",
            "prescription": {
                "name": "Amoxicillin 500mg", "dosage": "500mg",
                "frequency": "Three times daily", "prescribed_for": "Dental infection prevention",
                "duration_days": 7, "notes": "Complete full course even if feeling better.",
            },
            "diagnosis": {
                "condition_name": "Dental emergency — treated",
                "severity": "moderate", "status": "managed",
                "treatment_plan": "Soft foods for 48 hours. Avoid the treated area when brushing. Follow up if pain worsens.",
                "follow_up_recommended": 1, "follow_up_weeks": 2,
            },
            "referral": None, "lab_result": None,
        },

        # ── Vision ────────────────────────────────────────────────────────────
        "Routine eye exam": {
            "vibe": "clear_vision",
            "need_effects": {"stress": -3},
            "summary": "Eye exam completed. Prescription updated. Eyes are healthy.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Annual vision exam — routine",
                "severity": "mild", "status": "resolved",
                "treatment_plan": "Updated prescription issued. Next exam in 12 months.",
                "follow_up_recommended": 1, "follow_up_weeks": 52,
            },
            "referral": None,
            "lab_result": {
                "test_name": "Visual Acuity", "result_value": "Corrected to 20/20",
                "unit": "", "reference_range": "20/20 with correction",
                "status": "normal",
            },
        },

        # ── Physical Therapy ──────────────────────────────────────────────────
        "Birth control consultation": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -5},
            "summary": "Birth control consultation completed. Method selected and prescription issued.",
            "prescription": {
                "name": "Oral Contraceptive", "dosage": "1 tablet",
                "frequency": "Once daily at the same time each day",
                "prescribed_for": "Contraception",
                "duration_days": 90,
                "notes": "Take at the same time daily. Contact provider if you experience side effects.",
            },
            "diagnosis": {
                "condition_name": "Contraceptive management — active",
                "severity": "mild", "status": "managed",
                "treatment_plan": "Continue as prescribed. Follow up in 3 months.",
                "follow_up_recommended": 1, "follow_up_weeks": 12,
            },
            "referral": None, "lab_result": None,
        },
        "Menopause management": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -5, "recovery": 3},
            "summary": "Menopause management consultation completed. Symptom management plan established.",
            "prescription": {
                "name": "Hormone Therapy / Symptom Management",
                "dosage": "As prescribed", "frequency": "As directed",
                "prescribed_for": "Menopause symptom management",
                "duration_days": 90,
                "notes": "Monitor for changes and report any new symptoms.",
            },
            "diagnosis": {
                "condition_name": "Menopause — under management",
                "severity": "mild", "status": "managed",
                "treatment_plan": "Hormone therapy and lifestyle adjustments. Follow up in 3 months.",
                "follow_up_recommended": 1, "follow_up_weeks": 12,
            },
            "referral": None, "lab_result": None,
        },
        "Miscarriage / pregnancy loss support": {
            "vibe": "new_diagnosis_processing",
            "need_effects": {"stress": -8, "purpose": 3},
            "summary": "Pregnancy loss support visit completed. Physical recovery assessed. Grief support resources provided.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Pregnancy loss — support and recovery",
                "severity": "significant", "status": "active",
                "treatment_plan": "Physical recovery monitoring. Grief counseling strongly recommended. Follow up in 4 weeks.",
                "follow_up_recommended": 1, "follow_up_weeks": 4,
            },
            "referral": {
                "referral_to_doctor": "dr_fontaine",
                "referral_to_specialty": "mental_health",
                "urgency": "soon",
                "reason": "Grief counseling following pregnancy loss.",
            },
            "lab_result": None,
        },

        "Physical therapy session": {
            "vibe": "building_strength",
            "need_effects": {"recovery": 8, "stress": -5},
            "summary": "Physical therapy session completed. Good progress. Continue prescribed home exercises.",
            "prescription": None,
            "diagnosis": {
                "condition_name": "Physical therapy — in progress",
                "severity": "mild", "status": "managed",
                "treatment_plan": "Continue home exercise program. Next session as scheduled.",
                "follow_up_recommended": 1, "follow_up_weeks": 1,
            },
            "referral": None, "lab_result": None,
        },

        # ── Urgent Care ───────────────────────────────────────────────────────
        "Urgent care visit": {
            "vibe": "urgent_care_survivor",
            "need_effects": {"recovery": -15, "stress": -8},
            "summary": "Urgent care visit completed. Treatment administered. Follow care instructions closely.",
            "prescription": _sick_prescription(concerns_lower),
            "diagnosis": _sick_diagnosis(concerns_lower, today),
            "referral": {
                "referral_to_doctor": "dr_reyes",
                "referral_to_specialty": "primary_care",
                "urgency": "routine",
                "reason": "Post urgent care follow-up with primary care provider.",
            },
            "lab_result": None,
        },
        "Emergency room visit": {
            "vibe": "urgent_care_survivor",
            "need_effects": {"recovery": -20, "stress": -10},
            "summary": "Emergency room visit completed. You are stable. Follow all discharge instructions.",
            "prescription": {
                "name": "Discharge Medications", "dosage": "As prescribed",
                "frequency": "As directed", "prescribed_for": "Emergency treatment follow-up",
                "duration_days": 7, "notes": "Complete full course. Return to ER if symptoms worsen.",
            },
            "diagnosis": {
                "condition_name": "Emergency visit — treated and stable",
                "severity": "significant", "status": "managed",
                "treatment_plan": "Follow discharge instructions. Rest. Follow up with primary care within 72 hours.",
                "follow_up_recommended": 1, "follow_up_weeks": 1,
            },
            "referral": {
                "referral_to_doctor": "dr_reyes",
                "referral_to_specialty": "primary_care",
                "urgency": "soon",
                "reason": "Post-emergency primary care follow-up within 72 hours.",
            },
            "lab_result": None,
        },

        # ── Allergy ───────────────────────────────────────────────────────────
        "Allergy testing": {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -5},
            "summary": "Allergy testing completed. Results reviewed with your provider.",
            "prescription": {
                "name": "Antihistamine", "dosage": "10mg",
                "frequency": "Once daily as needed", "prescribed_for": "Allergy management",
                "duration_days": 90, "notes": "Take as needed for symptoms. Non-drowsy formula prescribed.",
            },
            "diagnosis": {
                "condition_name": "Allergic response confirmed — under management",
                "severity": "mild", "status": "managed",
                "treatment_plan": "Allergen avoidance and antihistamine as needed. Immunotherapy discussed.",
                "follow_up_recommended": 1, "follow_up_weeks": 8,
            },
            "referral": None,
            "lab_result": {
                "test_name": "Allergy Panel", "result_value": "Positive for identified allergens",
                "unit": "", "reference_range": "No reactivity expected",
                "status": "abnormal",
            },
        },
    }

    # Try exact specialty match first, then fallback
    profile = profiles.get(specialty)
    if not profile:
        # Generic fallback for any unrecognized specialty
        profile = {
            "vibe": "health_checked_in",
            "need_effects": {"stress": -3},
            "summary": f"{specialty} appointment completed. Notes filed in your care profile.",
            "prescription": None, "diagnosis": None, "referral": None, "lab_result": None,
        }

    return profile


def _sick_prescription(concerns: str) -> dict | None:
    """Generate appropriate prescription based on sick visit concerns."""
    if any(w in concerns for w in ["infection", "bacterial", "strep", "uti", "sinus"]):
        return {
            "name": "Amoxicillin 500mg", "dosage": "500mg",
            "frequency": "Twice daily", "prescribed_for": "Bacterial infection",
            "duration_days": 10, "notes": "Complete full course. Take with food.",
        }
    if any(w in concerns for w in ["pain", "ache", "headache", "cramp", "inflam"]):
        return {
            "name": "Ibuprofen 400mg", "dosage": "400mg",
            "frequency": "Every 6 hours as needed", "prescribed_for": "Pain and inflammation",
            "duration_days": 7, "notes": "Take with food. Do not exceed 1200mg per day.",
        }
    if any(w in concerns for w in ["nausea", "vomit", "stomach", "digestive"]):
        return {
            "name": "Ondansetron 4mg", "dosage": "4mg",
            "frequency": "As needed for nausea", "prescribed_for": "Nausea relief",
            "duration_days": 5, "notes": "Allow to dissolve under tongue.",
        }
    if any(w in concerns for w in ["anxiety", "stress", "panic"]):
        return {
            "name": "Hydroxyzine 25mg", "dosage": "25mg",
            "frequency": "As needed", "prescribed_for": "Acute anxiety management",
            "duration_days": 14, "notes": "May cause drowsiness. Do not drive after taking.",
        }
    # Default sick visit
    return {
        "name": "Rest and Supportive Care", "dosage": "As needed",
        "frequency": "Rest, fluids, OTC as directed",
        "prescribed_for": "Viral illness / general sick visit",
        "duration_days": 7, "notes": "Rest, stay hydrated. Return if symptoms worsen after 72 hours.",
    }


def _sick_diagnosis(concerns: str, today: str) -> dict:
    """Generate appropriate diagnosis based on sick visit concerns."""
    if any(w in concerns for w in ["strep", "throat"]):
        condition, severity = "Streptococcal pharyngitis", "moderate"
    elif any(w in concerns for w in ["uti", "urinary", "bladder"]):
        condition, severity = "Urinary tract infection", "moderate"
    elif any(w in concerns for w in ["sinus", "sinusitis"]):
        condition, severity = "Acute sinusitis", "mild"
    elif any(w in concerns for w in ["flu", "influenza"]):
        condition, severity = "Influenza A/B", "moderate"
    elif any(w in concerns for w in ["cold", "runny", "cough", "congestion"]):
        condition, severity = "Upper respiratory infection", "mild"
    elif any(w in concerns for w in ["migraine", "headache"]):
        condition, severity = "Migraine / tension headache", "moderate"
    elif any(w in concerns for w in ["anxiety", "panic"]):
        condition, severity = "Acute anxiety episode", "moderate"
    else:
        condition, severity = "Acute illness — general", "mild"

    return {
        "condition_name": condition,
        "severity": severity, "status": "active",
        "treatment_plan": "Rest, hydration, and medications as prescribed. Return if symptoms worsen.",
        "follow_up_recommended": 0, "follow_up_weeks": None,
    }


# ── Schemas ───────────────────────────────────────────────────────────────────

class UpdateProfile(BaseModel):
    token: str
    blood_type: str | None = None
    allergies: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_uuid: str | None = None
    primary_doctor_id: str | None = None


class ChangeInsurance(BaseModel):
    token: str
    insurance_plan: str


class ScheduleAppointment(BaseModel):
    token: str
    appointment_type: str
    specialty: str
    doctor_id: str
    scheduled_date: str      # YYYY-MM-DD
    scheduled_time: str | None = None
    concerns: str | None = None


class CompleteAppointment(BaseModel):
    token: str


class AddVaccination(BaseModel):
    token: str
    vaccine_name: str
    date_administered: str
    next_due_date: str | None = None
    administered_by: str | None = None
    lot_number: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_player(token: str, db):
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM players WHERE token = $1 AND is_banned = 0", token)
        return dict(row) if row else None
    else:
        async with db.execute(
            "SELECT * FROM players WHERE token = ? AND is_banned = 0", (token,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _get_or_create_health_profile(player_id: int, db) -> dict:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM healthcare_profiles WHERE player_id = $1", player_id)
        if not row:
            await db.execute(
                "INSERT INTO healthcare_profiles (player_id) VALUES ($1) ON CONFLICT DO NOTHING",
                player_id)
            row = await db.fetchrow(
                "SELECT * FROM healthcare_profiles WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_profiles WHERE player_id = ?", (player_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT OR IGNORE INTO healthcare_profiles (player_id) VALUES (?)", (player_id,))
            await db.commit()
            async with db.execute(
                "SELECT * FROM healthcare_profiles WHERE player_id = ?", (player_id,)
            ) as cur:
                row = await cur.fetchone()
    return dict(row) if row else {}


def _get_copay(insurance_plan: str, copay_category: str) -> float:
    plan = INSURANCE_PLANS.get(insurance_plan, INSURANCE_PLANS["uninsured"])
    key  = f"copay_{copay_category}"
    return plan.get(key, plan["copay_primary"])


# ── GET /healthcare/profile ───────────────────────────────────────────────────

@router.get("/profile")
async def get_profile(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    profile = await _get_or_create_health_profile(player["id"], db)
    plan    = INSURANCE_PLANS.get(profile.get("insurance_plan", "uninsured"), INSURANCE_PLANS["uninsured"])
    return {"profile": profile, "insurance": plan}


# ── POST /healthcare/profile ──────────────────────────────────────────────────

@router.post("/profile")
async def update_profile(body: UpdateProfile, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    await _get_or_create_health_profile(player_id, db)

    fields = {}
    if body.blood_type is not None:            fields["blood_type"] = body.blood_type
    if body.allergies is not None:             fields["allergies"] = body.allergies
    if body.emergency_contact_name is not None: fields["emergency_contact_name"] = body.emergency_contact_name
    if body.emergency_contact_uuid is not None: fields["emergency_contact_uuid"] = body.emergency_contact_uuid
    if body.primary_doctor_id is not None:     fields["primary_doctor_id"] = body.primary_doctor_id

    if not fields:
        return {"status": "no_changes"}

    if is_postgres():
        sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        await db.execute(
            f"UPDATE healthcare_profiles SET {sets} WHERE player_id = $1",
            player_id, *fields.values())
    else:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await db.execute(
            f"UPDATE healthcare_profiles SET {sets} WHERE player_id = ?",
            (*fields.values(), player_id))
        await db.commit()

    return {"status": "updated"}


# ── GET /healthcare/doctors ───────────────────────────────────────────────────

@router.get("/doctors")
async def list_doctors(specialty: str | None = None):
    if specialty:
        doctor_ids = SPECIALTY_DOCTORS.get(specialty, list(DOCTORS.keys()))
        docs = [DOCTORS[did] for did in doctor_ids if did in DOCTORS]
    else:
        docs = list(DOCTORS.values())
    return {"doctors": docs}


# ── GET /healthcare/insurance-plans ──────────────────────────────────────────

@router.get("/insurance-plans")
async def list_insurance_plans():
    return {"plans": list(INSURANCE_PLANS.values())}


# ── POST /healthcare/insurance ────────────────────────────────────────────────

@router.post("/insurance")
async def change_insurance(body: ChangeInsurance, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if body.insurance_plan not in INSURANCE_PLANS:
        raise HTTPException(status_code=400, detail="Unknown insurance plan.")

    player_id = player["id"]
    await _get_or_create_health_profile(player_id, db)

    if is_postgres():
        await db.execute(
            "UPDATE healthcare_profiles SET insurance_plan = $1 WHERE player_id = $2",
            body.insurance_plan, player_id)
    else:
        await db.execute(
            "UPDATE healthcare_profiles SET insurance_plan = ? WHERE player_id = ?",
            (body.insurance_plan, player_id))
        await db.commit()

    plan = INSURANCE_PLANS[body.insurance_plan]
    await push_notification(
        player_id=player_id, app_source="healthcare",
        title=f"Insurance updated: {plan['name']} 🏥",
        body="Your coverage is active. You can schedule appointments in MyChart.",
        priority="low", db=db)

    return {"status": "updated", "plan": plan}


# ── POST /healthcare/appointments/schedule ────────────────────────────────────

@router.post("/appointments/schedule")
async def schedule_appointment(body: ScheduleAppointment, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # Validate doctor
    if body.doctor_id not in DOCTORS:
        raise HTTPException(status_code=400, detail="Unknown doctor.")

    doctor = DOCTORS[body.doctor_id]

    # Validate date is future
    try:
        appt_date = date.fromisoformat(body.scheduled_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")
    if appt_date < date.today():
        raise HTTPException(status_code=400, detail="Appointment must be scheduled for a future date.")

    # Get insurance and calculate copay
    profile   = await _get_or_create_health_profile(player_id, db)
    insurance = profile.get("insurance_plan", "uninsured")
    appt_type = APPOINTMENT_TYPES.get(body.appointment_type, {})
    copay_cat = appt_type.get("copay_category", "primary")
    copay     = _get_copay(insurance, copay_cat)

    # Insert appointment
    if is_postgres():
        appt_id = await db.fetchval(
            """INSERT INTO healthcare_appointments
               (player_id, appointment_type, specialty, doctor_id, doctor_name,
                scheduled_date, scheduled_time, concerns, copay_paid)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
            player_id, body.appointment_type, body.specialty,
            body.doctor_id, doctor["name"], body.scheduled_date,
            body.scheduled_time, body.concerns, copay)
    else:
        async with db.execute(
            """INSERT INTO healthcare_appointments
               (player_id, appointment_type, specialty, doctor_id, doctor_name,
                scheduled_date, scheduled_time, concerns, copay_paid)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (player_id, body.appointment_type, body.specialty,
             body.doctor_id, doctor["name"], body.scheduled_date,
             body.scheduled_time, body.concerns, copay)
        ) as cur:
            appt_id = cur.lastrowid
        await db.commit()

    # Deduct copay from wallet
    if copay > 0:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        if is_postgres():
            await db.execute(
                """UPDATE wallets SET balance = GREATEST(0, balance - $1),
                   total_spent = total_spent + $2, last_updated = $3
                   WHERE player_id = $4""",
                copay, copay, now, player_id)
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES ($1, $2, 'purchase', $3, $4)""",
                player_id, -copay,
                f"Healthcare copay: {body.specialty} with {doctor['name']}", now)
        else:
            await db.execute(
                """UPDATE wallets SET balance = MAX(0, balance - ?),
                   total_spent = total_spent + ?, last_updated = ?
                   WHERE player_id = ?""",
                (copay, copay, now, player_id))
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES (?, ?, 'purchase', ?, ?)""",
                (player_id, -copay,
                 f"Healthcare copay: {body.specialty} with {doctor['name']}", now))
            await db.commit()

    # Fire notification
    time_str = f" at {body.scheduled_time}" if body.scheduled_time else ""
    await push_notification(
        player_id=player_id, app_source="healthcare",
        title=f"Appointment scheduled 🏥",
        body=f"{body.specialty} with {doctor['name']} on {body.scheduled_date}{time_str}. Copay: ✦{copay:.0f}",
        priority="normal", db=db)

    return {
        "status": "scheduled", "appointment_id": appt_id,
        "doctor": doctor["name"], "date": body.scheduled_date,
        "copay": copay, "insurance_plan": insurance,
    }


# ── GET /healthcare/appointments ─────────────────────────────────────────────

@router.get("/appointments")
async def list_appointments(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM healthcare_appointments WHERE player_id = $1
               ORDER BY scheduled_date DESC LIMIT 50""", player_id)
    else:
        async with db.execute(
            """SELECT * FROM healthcare_appointments WHERE player_id = ?
               ORDER BY scheduled_date DESC LIMIT 50""", (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    appts = [dict(r) for r in rows]
    for a in appts:
        a["doctor_info"] = DOCTORS.get(a["doctor_id"], {})

    upcoming = [a for a in appts if a["status"] == "scheduled"
                and a["scheduled_date"] >= date.today().isoformat()]
    past     = [a for a in appts if a["status"] != "scheduled"
                or a["scheduled_date"] < date.today().isoformat()]

    return {"upcoming": upcoming, "past": past}


# ── GET /healthcare/appointments/{id} ────────────────────────────────────────

@router.get("/appointments/{appointment_id}")
async def get_appointment(appointment_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        appt = await db.fetchrow(
            "SELECT * FROM healthcare_appointments WHERE id = $1 AND player_id = $2",
            appointment_id, player_id)
        meds = await db.fetch(
            "SELECT * FROM healthcare_medications WHERE appointment_id = $1", appointment_id)
        conds = await db.fetch(
            "SELECT * FROM healthcare_conditions WHERE appointment_id = $1", appointment_id)
        refs = await db.fetch(
            "SELECT * FROM healthcare_referrals WHERE appointment_id = $1", appointment_id)
        labs = await db.fetch(
            "SELECT * FROM healthcare_lab_results WHERE appointment_id = $1", appointment_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_appointments WHERE id = ? AND player_id = ?",
            (appointment_id, player_id)
        ) as cur:
            appt = await cur.fetchone()
        async with db.execute(
            "SELECT * FROM healthcare_medications WHERE appointment_id = ?", (appointment_id,)
        ) as cur:
            meds = await cur.fetchall()
        async with db.execute(
            "SELECT * FROM healthcare_conditions WHERE appointment_id = ?", (appointment_id,)
        ) as cur:
            conds = await cur.fetchall()
        async with db.execute(
            "SELECT * FROM healthcare_referrals WHERE appointment_id = ?", (appointment_id,)
        ) as cur:
            refs = await cur.fetchall()
        async with db.execute(
            "SELECT * FROM healthcare_lab_results WHERE appointment_id = ?", (appointment_id,)
        ) as cur:
            labs = await cur.fetchall()

    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    result = dict(appt)
    result["doctor_info"]    = DOCTORS.get(result["doctor_id"], {})
    result["medications"]    = [dict(r) for r in meds]
    result["conditions"]     = [dict(r) for r in conds]
    result["referrals"]      = [dict(r) for r in refs]
    result["lab_results"]    = [dict(r) for r in labs]
    return result


# ── POST /healthcare/appointments/{id}/complete ───────────────────────────────

@router.post("/appointments/{appointment_id}/complete")
async def complete_appointment(appointment_id: int, body: CompleteAppointment, db=Depends(get_db)):
    """
    Mark appointment complete and run all automated follow-up logic:
    - Issue prescription if applicable
    - Issue diagnosis if applicable
    - Issue referral if applicable
    - Issue lab result if applicable
    - Apply vibe
    - Fire notification
    - Advance IVF stage if applicable
    """
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    today_str = date.today().isoformat()

    if is_postgres():
        appt = await db.fetchrow(
            "SELECT * FROM healthcare_appointments WHERE id = $1 AND player_id = $2",
            appointment_id, player_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_appointments WHERE id = ? AND player_id = ?",
            (appointment_id, player_id)
        ) as cur:
            appt = await cur.fetchone()

    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if appt["status"] == "completed":
        return {"status": "already_completed"}

    profile  = await _get_or_create_health_profile(player_id, db)
    fp       = _get_followup_profile(appt["appointment_type"], appt["specialty"], appt["concerns"] or "")
    doctor   = DOCTORS.get(appt["doctor_id"], {"name": appt["doctor_name"]})

    # Mark complete
    if is_postgres():
        await db.execute(
            """UPDATE healthcare_appointments
               SET status = 'completed', completed_at = $1, summary = $2 WHERE id = $3""",
            today_str, fp["summary"], appointment_id)
    else:
        await db.execute(
            """UPDATE healthcare_appointments
               SET status = 'completed', completed_at = ?, summary = ? WHERE id = ?""",
            (today_str, fp["summary"], appointment_id))
        await db.commit()

    followups = []

    # ── Prescription ──────────────────────────────────────────────────────────
    if fp.get("prescription"):
        rx = fp["prescription"]
        end_date = None
        if rx.get("duration_days"):
            end_date = (date.today() + timedelta(days=rx["duration_days"])).isoformat()

        if is_postgres():
            await db.execute(
                """INSERT INTO healthcare_medications
                   (player_id, appointment_id, name, dosage, frequency, prescribed_for,
                    start_date, end_date, notes)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                player_id, appointment_id, rx["name"], rx.get("dosage"),
                rx.get("frequency"), rx.get("prescribed_for"),
                today_str, end_date, rx.get("notes"))
        else:
            await db.execute(
                """INSERT INTO healthcare_medications
                   (player_id, appointment_id, name, dosage, frequency, prescribed_for,
                    start_date, end_date, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (player_id, appointment_id, rx["name"], rx.get("dosage"),
                 rx.get("frequency"), rx.get("prescribed_for"),
                 today_str, end_date, rx.get("notes")))
            await db.commit()

        followups.append(f"Prescription: {rx['name']}")

    # ── Diagnosis ─────────────────────────────────────────────────────────────
    if fp.get("diagnosis"):
        dx = fp["diagnosis"]
        if is_postgres():
            await db.execute(
                """INSERT INTO healthcare_conditions
                   (player_id, appointment_id, condition_name, severity, status,
                    treatment_plan, follow_up_recommended, follow_up_weeks, diagnosed_date)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                player_id, appointment_id, dx["condition_name"], dx["severity"],
                dx["status"], dx.get("treatment_plan"),
                dx.get("follow_up_recommended", 0), dx.get("follow_up_weeks"),
                today_str)
        else:
            await db.execute(
                """INSERT INTO healthcare_conditions
                   (player_id, appointment_id, condition_name, severity, status,
                    treatment_plan, follow_up_recommended, follow_up_weeks, diagnosed_date)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (player_id, appointment_id, dx["condition_name"], dx["severity"],
                 dx["status"], dx.get("treatment_plan"),
                 dx.get("follow_up_recommended", 0), dx.get("follow_up_weeks"),
                 today_str))
            await db.commit()

        followups.append(f"Diagnosis noted: {dx['condition_name']}")

        # Apply additional vibe for significant/chronic diagnoses
        if dx["severity"] in ("significant", "chronic", "moderate"):
            vibe_key = "new_diagnosis_processing"
            if is_postgres():
                await db.execute(
                    """INSERT INTO vibes (player_id, vibe_key, is_negative)
                       VALUES ($1,$2,1) ON CONFLICT (player_id,vibe_key) DO NOTHING""",
                    player_id, vibe_key)
            else:
                await db.execute(
                    """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
                       VALUES (?,?,1)""", (player_id, vibe_key, 1))
                await db.commit()

    # ── Referral ──────────────────────────────────────────────────────────────
    if fp.get("referral"):
        ref = fp["referral"]
        if is_postgres():
            await db.execute(
                """INSERT INTO healthcare_referrals
                   (player_id, appointment_id, referral_to_doctor, referral_to_specialty,
                    urgency, reason)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                player_id, appointment_id, ref.get("referral_to_doctor"),
                ref["referral_to_specialty"], ref.get("urgency", "routine"),
                ref.get("reason"))
        else:
            await db.execute(
                """INSERT INTO healthcare_referrals
                   (player_id, appointment_id, referral_to_doctor, referral_to_specialty,
                    urgency, reason)
                   VALUES (?,?,?,?,?,?)""",
                (player_id, appointment_id, ref.get("referral_to_doctor"),
                 ref["referral_to_specialty"], ref.get("urgency", "routine"),
                 ref.get("reason")))
            await db.commit()

        followups.append(f"Referral: {ref['referral_to_specialty']}")

        ref_doctor = DOCTORS.get(ref.get("referral_to_doctor", ""), {})
        await push_notification(
            player_id=player_id, app_source="healthcare",
            title=f"Referral from {doctor['name']} 📋",
            body=f"You've been referred to {ref_doctor.get('name', ref['referral_to_specialty'])}. Tap to schedule.",
            priority="normal" if ref.get("urgency") != "urgent" else "urgent",
            db=db)

    # ── Lab Result ────────────────────────────────────────────────────────────
    if fp.get("lab_result"):
        lab = fp["lab_result"]
        if is_postgres():
            await db.execute(
                """INSERT INTO healthcare_lab_results
                   (player_id, appointment_id, test_name, result_value, unit,
                    reference_range, result_date, status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                player_id, appointment_id, lab["test_name"], lab.get("result_value"),
                lab.get("unit"), lab.get("reference_range"), today_str, lab.get("status", "normal"))
        else:
            await db.execute(
                """INSERT INTO healthcare_lab_results
                   (player_id, appointment_id, test_name, result_value, unit,
                    reference_range, result_date, status)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (player_id, appointment_id, lab["test_name"], lab.get("result_value"),
                 lab.get("unit"), lab.get("reference_range"), today_str, lab.get("status", "normal")))
            await db.commit()

        followups.append(f"Lab: {lab['test_name']}")

    # ── Vibe ──────────────────────────────────────────────────────────────────
    if fp.get("vibe"):
        vk = fp["vibe"]
        is_neg = 1 if vk in ("recovery_mode", "urgent_care_survivor", "health_anxiety",
                              "new_diagnosis_processing", "chronic_condition_vibe",
                              "ivf_exhausted", "ivf_anxious") else 0
        if is_postgres():
            await db.execute(
                """INSERT INTO vibes (player_id, vibe_key, is_negative)
                   VALUES ($1,$2,$3) ON CONFLICT (player_id,vibe_key) DO NOTHING""",
                player_id, vk, is_neg)
        else:
            await db.execute(
                """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
                   VALUES (?,?,?)""", (player_id, vk, is_neg))
            await db.commit()

    # ── IVF Stage Advance ─────────────────────────────────────────────────────
    ivf_advance = fp.get("ivf_stage_advance")
    if ivf_advance:
        if is_postgres():
            await db.execute(
                """UPDATE player_occurrences SET sub_stage = $1
                   WHERE player_id = $2 AND occurrence_key = 'ttc_ivf' AND is_resolved = 0""",
                ivf_advance, player_id)
        else:
            await db.execute(
                """UPDATE player_occurrences SET sub_stage = ?
                   WHERE player_id = ? AND occurrence_key = 'ttc_ivf' AND is_resolved = 0""",
                (ivf_advance, player_id))
            await db.commit()
        followups.append(f"IVF stage → {ivf_advance}")

    # ── Achievement stat ──────────────────────────────────────────────────────
    try:
        from app.services.achievements import increment_stat
        await increment_stat(player_id, "appointments_completed")
    except Exception:
        pass

    # ── Completion notification ───────────────────────────────────────────────
    await push_notification(
        player_id=player_id, app_source="healthcare",
        title=f"Appointment completed 🏥",
        body=f"Your {appt['specialty']} with {doctor['name']} is on file. " +
             (f"Notes added: {', '.join(followups[:2])}." if followups else "Summary in MyChart."),
        priority="normal", db=db)

    return {
        "status": "completed",
        "summary": fp["summary"],
        "follow_ups_issued": followups,
        "vibe_applied": fp.get("vibe"),
        "ivf_stage_advanced": ivf_advance,
    }


# ── POST /healthcare/appointments/{id}/cancel ─────────────────────────────────

@router.post("/appointments/{appointment_id}/cancel")
async def cancel_appointment(appointment_id: int, body: CompleteAppointment, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        appt = await db.fetchrow(
            "SELECT * FROM healthcare_appointments WHERE id = $1 AND player_id = $2",
            appointment_id, player_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_appointments WHERE id = ? AND player_id = ?",
            (appointment_id, player_id)
        ) as cur:
            appt = await cur.fetchone()

    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if appt["status"] == "completed":
        raise HTTPException(status_code=400, detail="Cannot cancel a completed appointment.")

    if is_postgres():
        await db.execute(
            "UPDATE healthcare_appointments SET status = 'cancelled' WHERE id = $1",
            appointment_id)
    else:
        await db.execute(
            "UPDATE healthcare_appointments SET status = 'cancelled' WHERE id = ?",
            (appointment_id,))
        await db.commit()

    # Partial copay refund (50%)
    if appt["copay_paid"] > 0:
        from datetime import datetime, timezone
        refund = appt["copay_paid"] * 0.5
        now    = datetime.now(timezone.utc).isoformat()
        if is_postgres():
            await db.execute(
                """UPDATE wallets SET balance = balance + $1,
                   total_earned = total_earned + $2, last_updated = $3
                   WHERE player_id = $4""",
                refund, refund, now, player_id)
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES ($1, $2, 'refund', $3, $4)""",
                player_id, refund, "Cancellation refund (50%)", now)
        else:
            await db.execute(
                """UPDATE wallets SET balance = balance + ?,
                   total_earned = total_earned + ?, last_updated = ?
                   WHERE player_id = ?""",
                (refund, refund, now, player_id))
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES (?, ?, 'refund', ?, ?)""",
                (player_id, refund, "Cancellation refund (50%)", now))
            await db.commit()

    return {"status": "cancelled", "refund": appt["copay_paid"] * 0.5}


# ── GET /healthcare/medications ───────────────────────────────────────────────

@router.get("/medications")
async def list_medications(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        rows = await db.fetch(
            "SELECT * FROM healthcare_medications WHERE player_id = $1 ORDER BY created_at DESC",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_medications WHERE player_id = ? ORDER BY created_at DESC",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    return {"medications": [dict(r) for r in rows]}


# ── POST /healthcare/medications/{id}/deactivate ──────────────────────────────

@router.post("/medications/{medication_id}/deactivate")
async def deactivate_medication(medication_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        await db.execute(
            """UPDATE healthcare_medications SET is_active = 0, end_date = $1
               WHERE id = $2 AND player_id = $3""",
            date.today().isoformat(), medication_id, player_id)
    else:
        await db.execute(
            """UPDATE healthcare_medications SET is_active = 0, end_date = ?
               WHERE id = ? AND player_id = ?""",
            (date.today().isoformat(), medication_id, player_id))
        await db.commit()

    return {"status": "deactivated"}


# ── GET /healthcare/conditions ────────────────────────────────────────────────

@router.get("/conditions")
async def list_conditions(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        rows = await db.fetch(
            "SELECT * FROM healthcare_conditions WHERE player_id = $1 ORDER BY diagnosed_date DESC",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_conditions WHERE player_id = ? ORDER BY diagnosed_date DESC",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    return {"conditions": [dict(r) for r in rows]}


# ── GET /healthcare/referrals ─────────────────────────────────────────────────

@router.get("/referrals")
async def list_referrals(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        rows = await db.fetch(
            "SELECT * FROM healthcare_referrals WHERE player_id = $1 ORDER BY created_at DESC",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_referrals WHERE player_id = ? ORDER BY created_at DESC",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["doctor_info"] = DOCTORS.get(d.get("referral_to_doctor", ""), {})
        result.append(d)

    return {"referrals": result}


# ── GET /healthcare/lab-results ───────────────────────────────────────────────

@router.get("/lab-results")
async def list_lab_results(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        rows = await db.fetch(
            "SELECT * FROM healthcare_lab_results WHERE player_id = $1 ORDER BY result_date DESC",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_lab_results WHERE player_id = ? ORDER BY result_date DESC",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    return {"lab_results": [dict(r) for r in rows]}


# ── GET /healthcare/vaccinations ──────────────────────────────────────────────

@router.get("/vaccinations")
async def list_vaccinations(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        rows = await db.fetch(
            "SELECT * FROM healthcare_vaccinations WHERE player_id = $1 ORDER BY date_administered DESC",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM healthcare_vaccinations WHERE player_id = ? ORDER BY date_administered DESC",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    return {"vaccinations": [dict(r) for r in rows]}


# ── POST /healthcare/vaccinations/add ─────────────────────────────────────────

@router.post("/vaccinations/add")
async def add_vaccination(body: AddVaccination, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        await db.execute(
            """INSERT INTO healthcare_vaccinations
               (player_id, vaccine_name, date_administered, next_due_date, administered_by, lot_number)
               VALUES ($1,$2,$3,$4,$5,$6)""",
            player_id, body.vaccine_name, body.date_administered,
            body.next_due_date, body.administered_by, body.lot_number)
    else:
        await db.execute(
            """INSERT INTO healthcare_vaccinations
               (player_id, vaccine_name, date_administered, next_due_date, administered_by, lot_number)
               VALUES (?,?,?,?,?,?)""",
            (player_id, body.vaccine_name, body.date_administered,
             body.next_due_date, body.administered_by, body.lot_number))
        await db.commit()

    return {"status": "added"}
