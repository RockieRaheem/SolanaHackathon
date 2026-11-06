from datetime import date
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session
from verification_client import authenticated_client

from harambeeone_api.database import get_engine
from harambeeone_api.models import FeeCategory, FeeStructure


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    group = client.get(f"/api/v1/schools/{school['id']}/classes").json()[0]
    code = f"V{str(uuid4())[:7]}".upper()
    category_id = plan_id = None
    try:
        category = client.post(
            "/api/v1/fee-categories",
            json={
                "school_id": school["id"],
                "name": "Verification fee",
                "code": code,
                "category_type": "other",
                "is_required": True,
                "is_recurring": True,
                "priority": 99,
            },
        )
        category.raise_for_status()
        category_id = category.json()["id"]
        plan = client.post(
            "/api/v1/fee-plans",
            json={
                "school_id": school["id"],
                "class_id": group["id"],
                "name": "Verification plan",
                "academic_year": 2099,
                "term": 3,
                "currency": "UGX",
                "items": [{"category_id": category_id, "amount": 100000}],
                "installments": [
                    {
                        "name": "Opening",
                        "amount": 50000,
                        "due_date": str(date(2099, 1, 1)),
                        "sort_order": 1,
                    },
                    {
                        "name": "Final",
                        "amount": 50000,
                        "due_date": str(date(2099, 2, 1)),
                        "sort_order": 2,
                    },
                ],
            },
        )
        plan.raise_for_status()
        plan_id = plan.json()["id"]
        assert float(plan.json()["total_amount"]) == 100000
        print("Fee configuration ready: category lines and installments reconcile")
    finally:
        with Session(get_engine()) as session:
            if plan_id:
                session.execute(delete(FeeStructure).where(FeeStructure.id == plan_id))
            if category_id:
                session.execute(delete(FeeCategory).where(FeeCategory.id == category_id))
            session.commit()


if __name__ == "__main__":
    main()
