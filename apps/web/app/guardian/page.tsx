"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Building2, HandHeart, LoaderCircle, ShieldCheck } from "lucide-react";
import PortalShell from "@/components/PortalShell";
import { clientFetch as fetch } from "@/lib/api/client";

type Learner = {
  student_id: string;
  learner_name: string;
  admission_no: string;
  relationship: string;
  is_primary: boolean;
  school_name: string;
};
type CampaignMedia = {
  status: "pending" | "approved" | "rejected";
  alt_text: string;
  review_note: string | null;
};
type SupportCase = {
  id: string;
  public_code: string;
  requirement_assignment_id: string | null;
  title: string;
  public_summary: string;
  private_context: string | null;
  need_category: string;
  target_amount: string;
  live_limit: string;
  status: string;
  review_notes: string | null;
  media: CampaignMedia | null;
};
type Referral = {
  id: string;
  student_id: string;
  school_name: string;
  learner_name: string;
  outstanding_snapshot: string;
  days_overdue_snapshot: number;
  priority_band: string;
  status: string;
  privacy_notice: string;
  gemma_processing: boolean;
  child_assent_status: string;
  public_media_consent: boolean;
  case: SupportCase | null;
};
type Obligation = {
  id: string | null;
  label: string;
  outstanding: string;
  suggested_category?: string;
};
type Obligations = { general: Obligation; requirements: Obligation[] };
const money = (value: string | number) =>
  `UGX ${Number(value).toLocaleString("en-UG")}`;

export default function GuardianPage() {
  const [learners, setLearners] = useState<Learner[]>([]),
    [referrals, setReferrals] = useState<Referral[]>([]);
  const [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        fetch("/api/backend/api/v1/guardian/learners"),
        fetch("/api/backend/api/v1/support/guardian/referrals"),
      ]);
      const learnersBody = await a.json(),
        referralsBody = await b.json();
      if (!a.ok || !b.ok)
        throw new Error(
          learnersBody.detail ||
            referralsBody.detail ||
            "Guardian workspace could not be loaded.",
        );
      setLearners(learnersBody);
      setReferrals(referralsBody);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Guardian workspace could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const updateReferral = useCallback((updated: Referral) => {
    setReferrals((current) => {
      const found = current.some((item) => item.id === updated.id);
      return found
        ? current.map((item) => (item.id === updated.id ? updated : item))
        : [updated, ...current];
    });
  }, []);
  async function requestSupport(studentId: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(
        "/api/backend/api/v1/support/guardian/referrals",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ student_id: studentId }),
        },
      );
      const body = (await response.json()) as Referral & { detail?: unknown };
      if (!response.ok)
        throw new Error(
          apiError(body.detail, "Support request could not be started."),
        );
      setNotice(
        "Private support request started. Review the privacy choices below before preparing a case.",
      );
      updateReferral(body);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Support request could not be started.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function decide(event: FormEvent<HTMLFormElement>, item: Referral) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    const form = new FormData(event.currentTarget);
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const action =
      submitter instanceof HTMLButtonElement ? submitter.value : "";
    try {
      const response = await fetch(
        `/api/backend/api/v1/support/guardian/referrals/${item.id}/consent`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action,
            privacy_notice_version: "2026-11-v2",
            guardian_authority_confirmed: form.get("authority") === "on",
            age_verification_method: form.get("age_verification_method"),
            anonymous_publication: form.get("publication") === "anonymous",
            public_identity_consent: form.get("publication") === "identified",
            public_media_consent:
              form.get("publication") === "identified" &&
              form.get("public_media_consent") === "on",
            gemma_processing: form.get("gemma_processing") === "on",
            cross_border_processing:
              form.get("cross_border_processing") === "on",
            child_assent_status: form.get("child_assent_status"),
            child_assent_reason: form.get("child_assent_reason") || null,
          }),
        },
      );
      const body = (await response.json()) as Referral & { detail?: unknown };
      if (!response.ok)
        throw new Error(
          apiError(body.detail, "Consent decision could not be saved."),
        );
      setNotice(
        body.status === "consented"
          ? "Consent recorded. You can now prepare the private support request."
          : "The school was informed that you declined participation.",
      );
      updateReferral(body);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Consent decision could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function withdraw(id: string) {
    if (
      !confirm(
        "Withdraw participation and stop new fundraising? Existing financial receipts will remain preserved.",
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(
        `/api/backend/api/v1/support/guardian/referrals/${id}/withdraw`,
        { method: "POST" },
      );
      const body = (await response.json()) as Referral & { detail?: unknown };
      if (!response.ok)
        throw new Error(
          apiError(body.detail, "Consent could not be withdrawn."),
        );
      setNotice("Consent withdrawn. No new fundraising is permitted.");
      updateReferral(body);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Consent could not be withdrawn.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (loading)
    return (
      <PortalShell label="Guardian workspace">
        <div className="portal-state">
          <LoaderCircle className="spin" />
          Loading your secure learner links…
        </div>
      </PortalShell>
    );
  return (
    <PortalShell label="Guardian workspace">
      <section className="portal-intro">
        <span>Private learner support</span>
        <h1>Your linked learner accounts</h1>
        <p>
          Only you and authorized school staff can see these identities. Public
          identity appears only after your explicit consent, learner assent and
          school safeguarding approval.
        </p>
      </section>
      {error && (
        <div className="portal-error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="success-banner" role="status">
          {notice}
        </div>
      )}
      <div className="guardian-learner-grid">
        {learners.map((item) => (
          <article key={item.student_id}>
            <div>
              <Building2 />
              <span>{item.school_name}</span>
            </div>
            <h2>{item.learner_name}</h2>
            <p>
              {item.admission_no} · {item.relationship}
              {item.is_primary ? " · Primary guardian" : ""}
            </p>
            <footer>
              <span>
                <ShieldCheck size={16} />
                Verified school link
              </span>
              <button
                className="btn primary"
                disabled={
                  busy ||
                  referrals.some(
                    (referral) => referral.student_id === item.student_id,
                  )
                }
                onClick={() => requestSupport(item.student_id)}
              >
                {referrals.some(
                  (referral) => referral.student_id === item.student_id,
                )
                  ? "Support request active"
                  : "Start support request"}
              </button>
            </footer>
          </article>
        ))}
      </div>
      <section className="portal-section guardian-referrals">
        <h2>Support requests</h2>
        {referrals.map((item) => (
          <article key={item.id} className="guardian-referral">
            <header>
              <div>
                <span>
                  {item.school_name} · {item.priority_band} priority
                </span>
                <h3>{item.learner_name}</h3>
                <p>
                  {money(item.outstanding_snapshot)} ·{" "}
                  {item.days_overdue_snapshot} days overdue
                </p>
              </div>
              <strong>
                {(item.case?.status ?? item.status).replaceAll("_", " ")}
              </strong>
            </header>
            {item.status === "awaiting_consent" && (
              <form onSubmit={(event) => decide(event, item)}>
                <div className="privacy-notice">
                  <ShieldCheck />
                  <p>
                    <strong>Before you decide</strong>
                    {item.privacy_notice}
                  </p>
                </div>
                <label className="portal-check">
                  <input name="authority" type="checkbox" />I confirm I am
                  authorized to decide for this learner.
                </label>
                <label>
                  How the learner&apos;s age was checked
                  <select name="age_verification_method" required>
                    <option value="school_record">School record</option>
                    <option value="birth_certificate">Birth certificate</option>
                    <option value="guardian_declaration">
                      Guardian declaration
                    </option>
                    <option value="national_id">
                      National ID / NIN record
                    </option>
                    <option value="other">Other reliable record</option>
                  </select>
                </label>
                <label>
                  Learner&apos;s view
                  <select name="child_assent_status">
                    <option value="agreed">Learner agreed</option>
                    <option value="declined">Learner declined</option>
                    <option value="not_applicable">
                      Too young / not applicable
                    </option>
                    <option value="unable_to_express">
                      Unable to express a view
                    </option>
                  </select>
                </label>
                <label>
                  Reason when assent is unavailable
                  <input name="child_assent_reason" maxLength={240} />
                </label>
                <label>
                  Public campaign identity
                  <select name="publication" defaultValue="anonymous" required>
                    <option value="anonymous">
                      Anonymous — do not publish the learner name or photo
                    </option>
                    <option value="identified">
                      Identified — publish the learner name after school approval
                    </option>
                  </select>
                  <small>
                    Donors never see the admission number, contacts or private family context.
                  </small>
                </label>
                <label className="portal-check">
                  <input name="public_media_consent" type="checkbox" />
                  I separately consent to a school-reviewed learner photograph
                  being shown with an identified campaign.
                </label>
                <label className="portal-check">
                  <input name="gemma_processing" type="checkbox" />I separately
                  consent to privacy-minimized Gemma assistance.
                </label>
                <label className="portal-check">
                  <input name="cross_border_processing" type="checkbox" />I
                  separately consent to Gemma processing outside Uganda.
                </label>
                <div className="referral-actions">
                  <button
                    name="action"
                    value="decline"
                    className="btn"
                    formNoValidate
                    disabled={busy}
                  >
                    Decline
                  </button>
                  <button
                    name="action"
                    value="grant"
                    className="btn primary"
                    disabled={busy}
                  >
                    Give selected consent
                  </button>
                </div>
              </form>
            )}
            {item.status === "consented" && (
              <>
                <div className="consent-summary">
                  <HandHeart />
                  <p>
                    <strong>Consent recorded</strong>Gemma:{" "}
                    {item.gemma_processing ? "allowed" : "not allowed"} ·
                    Learner view: {item.child_assent_status}.
                  </p>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => withdraw(item.id)}
                  >
                    Withdraw
                  </button>
                </div>
                {(!item.case ||
                  ["draft", "changes_requested"].includes(
                    item.case.status,
                  )) && (
                  <CaseEditor
                    referral={item}
                    afterSave={(message, supportCase, submitted) => {
                      setNotice(message);
                      updateReferral({
                        ...item,
                        status: submitted ? "case_submitted" : item.status,
                        case: supportCase,
                      });
                    }}
                  />
                )}
              </>
            )}
            {item.case &&
              (item.status === "case_submitted" ||
                (item.status === "consented" &&
                  !["draft", "changes_requested"].includes(
                    item.case.status,
                  ))) && (
                <div className="case-review-state">
                  <ShieldCheck />
                  <div>
                    <strong>
                      {item.case.status === "approved"
                        ? "Approved for publication"
                        : item.case.status === "published"
                          ? "Campaign published"
                          : "School review in progress"}
                    </strong>
                    <p>
                      {item.case.status === "published"
                        ? "The consented beneficiary campaign is now public."
                        : item.case.status === "approved"
                          ? "An institution owner has approved the case."
                          : `The school received your request for ${money(item.case.target_amount)}.`}
                    </p>
                    {["published", "funded", "closed"].includes(
                      item.case.status,
                    ) && (
                      <Link
                        className="btn"
                        href={`/support/${item.case.public_code}`}
                      >
                        View public campaign
                      </Link>
                    )}
                  </div>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => withdraw(item.id)}
                  >
                    Withdraw consent
                  </button>
                </div>
              )}
            {["declined", "withdrawn"].includes(item.status) && (
              <p className="closed-referral">
                Participation is {item.status}. No campaign may be published
                from this referral.
              </p>
            )}
          </article>
        ))}
        {!referrals.length && (
          <div className="portal-empty">
            <HandHeart />
            <h2>No support referrals</h2>
            <p>
              Start a private request from a linked learner card. The school
              must review it before publication.
            </p>
            <Link className="btn" href="/support">
              View public campaigns
            </Link>
          </div>
        )}
      </section>
    </PortalShell>
  );
}

function CaseEditor({
  referral,
  afterSave,
}: {
  referral: Referral;
  afterSave: (
    message: string,
    supportCase: SupportCase,
    submitted: boolean,
  ) => void;
}) {
  const current = referral.case;
  const [obligations, setObligations] = useState<Obligations | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [obligationId, setObligationId] = useState(
      current?.requirement_assignment_id ?? "",
    ),
    [needCategory, setNeedCategory] = useState(
      current?.need_category ?? "fees",
    );
  useEffect(() => {
    fetch(
      `/api/backend/api/v1/support/guardian/referrals/${referral.id}/obligations`,
    )
      .then(async (response) => {
        const body = (await safeBody(response)) as
          (Obligations & { detail?: unknown }) | null;
        if (!response.ok)
          throw new Error(
            apiError(
              body?.detail,
              `Verified obligations could not be loaded (server error ${response.status}).`,
            ),
          );
        if (!body)
          throw new Error("Verified obligations returned an invalid response.");
        setObligations(body);
      })
      .catch((reason) =>
        setError(
          reason instanceof Error
            ? reason.message
            : "Verified obligations could not be loaded.",
        ),
      );
  }, [referral.id]);
  const all = obligations
    ? [obligations.general, ...obligations.requirements]
    : [];
  const selected =
    all.find((item) => (item.id ?? "") === obligationId) ??
    obligations?.general;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const action =
      submitter instanceof HTMLButtonElement ? submitter.value : "save";
    try {
      const response = await fetch(
        `/api/backend/api/v1/support/guardian/referrals/${referral.id}/case`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            requirement_assignment_id: obligationId || null,
            title: form.get("title"),
            public_summary: form.get("public_summary"),
            private_context: form.get("private_context"),
            need_category: form.get("need_category"),
            target_amount: Number(form.get("target_amount")),
          }),
        },
      );
      const body = (await safeBody(response)) as
        (SupportCase & { detail?: unknown }) | null;
      if (!response.ok)
        throw new Error(
          apiError(
            body?.detail,
            `Your draft could not be saved (server error ${response.status}).`,
          ),
        );
      if (!body) throw new Error("Your draft returned an invalid response.");
      const photo = form.get("campaign_photo") as File | null;
      if (photo && photo.size > 0) {
        if (photo.size > 1_500_000)
          throw new Error("Use a learner photo no larger than 1.5 MB.");
        const photoResponse = await fetch(
          `/api/backend/api/v1/support/guardian/referrals/${referral.id}/media`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              image_base64: await fileBase64(photo),
              image_mime_type: photo.type,
              alt_text: form.get("campaign_photo_alt_text"),
            }),
          },
        );
        const photoBody = (await safeBody(photoResponse)) as
          (CampaignMedia & { detail?: unknown }) | null;
        if (!photoResponse.ok)
          throw new Error(
            apiError(photoBody?.detail, "The learner photo could not be submitted."),
          );
        body.media = photoBody;
      }
      if (action === "submit") {
        const submitted = await fetch(
          `/api/backend/api/v1/support/guardian/referrals/${referral.id}/case/submit`,
          { method: "POST" },
        );
        const submittedBody = (await safeBody(submitted)) as
          (SupportCase & { detail?: unknown }) | null;
        if (!submitted.ok)
          throw new Error(
            apiError(
              submittedBody?.detail,
              `Your case could not be submitted (server error ${submitted.status}).`,
            ),
          );
        if (!submittedBody)
          throw new Error("Case submission returned an invalid response.");
        afterSave(
          "Your private case was submitted to the school for review.",
          submittedBody,
          true,
        );
      } else
        afterSave(
          "Private draft saved. Nothing has been published.",
          body,
          false,
        );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Your case could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="guardian-case-editor" onSubmit={submit}>
      <div className="case-editor-heading">
        <div>
          <span>Private case preparation</span>
          <h4>
            {current?.status === "changes_requested"
              ? "Revise the school request"
              : "Prepare the support request"}
          </h4>
        </div>
        <small>
          Drafts are visible only to you and authorized school staff.
        </small>
      </div>
      {current?.review_notes && (
        <div className="change-request">
          <strong>School requested changes</strong>
          <p>{current.review_notes}</p>
        </div>
      )}
      <label>
        Verified obligation
        <select
          value={obligationId}
          onChange={(event) => {
            const nextId = event.target.value;
            setObligationId(nextId);
            const next = all.find((item) => (item.id ?? "") === nextId);
            setNeedCategory(
              next?.suggested_category ?? (nextId ? "other" : "fees"),
            );
          }}
          disabled={!obligations}
        >
          <option value="">
            {obligations
              ? `${obligations.general.label} · ${money(obligations.general.outstanding)}`
              : "Loading verified balances…"}
          </option>
          {obligations?.requirements.map((item) => (
            <option key={item.id!} value={item.id!}>
              {item.label} · {money(item.outstanding)}
            </option>
          ))}
        </select>
      </label>
      <div className="guardian-case-fields">
        <label>
          Need category
          <select
            name="need_category"
            value={needCategory}
            onChange={(event) => setNeedCategory(event.target.value)}
          >
            <option value="fees">School fees</option>
            <option value="examination">Examination</option>
            <option value="uniform">Uniform</option>
            <option value="learning_materials">Learning materials</option>
            <option value="meals">Meals</option>
            <option value="transport">Transport</option>
            <option value="other">Other</option>
          </select>
        </label>
        <label>
          Requested support (UGX)
          <input
            key={`${obligationId}:${selected?.outstanding ?? ""}`}
            name="target_amount"
            type="number"
            min="1"
            max={selected?.outstanding}
            defaultValue={current?.target_amount ?? selected?.outstanding}
            required
          />
          <small>
            Maximum live balance: {money(selected?.outstanding ?? 0)}
          </small>
        </label>
      </div>
      <label>
        Private context for school review
        <textarea
          name="private_context"
          maxLength={1500}
          minLength={20}
          defaultValue={current?.private_context ?? ""}
          required
          placeholder="Explain the situation factually. Donors will never see this text."
        />
      </label>
      <div className="public-preview">
        <strong>Public campaign story</strong>
        <p>
          The consented name and approved photograph are added securely. Do not
          type an admission number, exact class, contact or private family
          detail here.
        </p>
        <label>
          Campaign title
          <input
            name="title"
            minLength={4}
            maxLength={120}
            defaultValue={current?.title ?? ""}
            required
            placeholder="Help a learner clear a verified school balance"
          />
        </label>
        <label>
          Public summary
          <textarea
            name="public_summary"
            minLength={20}
            maxLength={500}
            defaultValue={current?.public_summary ?? ""}
            required
            placeholder="Describe only the verified school obligation and intended outcome."
          />
        </label>
        {referral.public_media_consent && (
          <div className="guardian-photo-submit">
            <strong>Learner photo for school review</strong>
            <p>
              This remains private until an institution owner completes a
              safeguarding review. Metadata is removed and the image is resized.
            </p>
            {current?.media && (
              <div className={`media-review-state ${current.media.status}`}>
                <span>Photo {current.media.status.replaceAll("_", " ")}</span>
                {current.media.review_note && <small>{current.media.review_note}</small>}
              </div>
            )}
            <label>
              {current?.media ? "Replace learner photo" : "Learner photo"}
              <input
                name="campaign_photo"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                required={!current?.media}
              />
              <small>JPEG, PNG or WebP · 320×240 minimum · 1.5 MB maximum</small>
            </label>
            <label>
              Accessible photo description
              <input
                name="campaign_photo_alt_text"
                minLength={8}
                maxLength={160}
                defaultValue={current?.media?.alt_text ?? ""}
                required={!current?.media}
                placeholder="Learner smiling in the school courtyard"
              />
            </label>
          </div>
        )}
      </div>
      {error && (
        <div className="portal-error" role="alert">
          {error}
        </div>
      )}
      <footer>
        <button
          className="btn"
          name="action"
          value="save"
          disabled={busy || !obligations}
        >
          {busy ? "Saving…" : "Save private draft"}
        </button>
        <button
          className="btn primary"
          name="action"
          value="submit"
          disabled={busy || !obligations}
        >
          Submit to school
        </button>
      </footer>
    </form>
  );
}

function apiError(detail: unknown, fallback: string) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail))
    return (
      detail
        .map((item) => (item as { msg?: string })?.msg)
        .filter(Boolean)
        .join(" ") || fallback
    );
  return fallback;
}
function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(new Error("The learner photo could not be read."));
    reader.readAsDataURL(file);
  });
}

async function safeBody(response: Response) {
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("application/json")) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}
