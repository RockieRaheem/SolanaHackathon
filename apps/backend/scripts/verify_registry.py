from sqlalchemy import text
from verification_client import authenticated_client

from harambeeone_api.database import get_engine


def main() -> None:
    client = authenticated_client()
    schools_response = client.get("/api/v1/schools")
    schools_response.raise_for_status()
    schools = schools_response.json()
    if not schools:
        raise RuntimeError("No school has been configured")

    school_id = schools[0]["id"]
    classes_response = client.get(f"/api/v1/schools/{school_id}/classes")
    classes_response.raise_for_status()
    students_response = client.get("/api/v1/students", params={"school_id": school_id})
    students_response.raise_for_status()
    fees_response = client.get("/api/v1/fee-structures", params={"school_id": school_id})
    fees_response.raise_for_status()
    with get_engine().connect() as connection:
        protected_tables = connection.execute(
            text(
                "select count(*) from pg_class "
                "where relnamespace = 'public'::regnamespace "
                "and relname = any(:tables) and relrowsecurity"
            ),
            {
                "tables": [
                    "schools",
                    "academic_classes",
                    "streams",
                    "people",
                    "students",
                    "enrollments",
                    "guardian_links",
                    "fee_structures",
                    "student_fee_assignments",
                    "payments",
                    "payment_allocations",
                    "ledger_entries",
                    "stellar_anchors",
                ]
            },
        ).scalar_one()
    if protected_tables != 13:
        raise RuntimeError("Registry and finance RLS protection is incomplete")
    print(
        "Registry ready: "
        f"{len(schools)} school, {len(classes_response.json())} classes, "
        f"{students_response.json()['total']} learners, "
        f"{len(fees_response.json())} fee structures, "
        f"{protected_tables} RLS-protected tables"
    )


if __name__ == "__main__":
    main()
