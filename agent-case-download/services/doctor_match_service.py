"""Strict-then-fuzzy doctor identity resolution for portal-scraped data."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from thefuzz import fuzz


@dataclass(frozen=True)
class DoctorIdentity:
    """Canonical doctor fields used by the matching engine."""

    account_id: str = ""
    doctor_id: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    zip_code: str = ""
    practice: str = ""


@dataclass(frozen=True)
class DoctorMatch:
    doctor: DoctorIdentity
    method: str
    confidence: float
    field_scores: Mapping[str, float]


class DoctorIdentificationError(LookupError):
    """Raised when a doctor is missing, below threshold, or ambiguous."""


class MatchNotifier(Protocol):
    def send(self, scraped: DoctorIdentity, reason: str) -> None: ...


class GraphDoctorMatchNotifier:
    """Send identification failures through Microsoft Graph application mail."""

    def __init__(self, recipient: str | None = None) -> None:
        self.recipient = recipient or os.getenv("DOCTOR_MATCH_ALERT_RECIPIENT")

    def send(self, scraped: DoctorIdentity, reason: str) -> None:
        settings = {
            "tenant_id": os.getenv("MAIL_SENDER_TENANT_ID"),
            "client_id": os.getenv("MAIL_SENDER_CLIENT_ID"),
            "client_secret": os.getenv("MAIL_SENDER_CLIENT_SECRET"),
            "sender": os.getenv("MAIL_SENDER_ADDRESS"),
        }
        recipient = self.recipient or settings["sender"]
        missing = [key for key, value in settings.items() if not value]
        if not recipient:
            missing.append("recipient")
        if missing:
            raise RuntimeError(
                "Missing Microsoft Graph configuration: " + ", ".join(missing)
            )

        token_request = Request(
            f"https://login.microsoftonline.com/{settings['tenant_id']}/oauth2/v2.0/token",
            data=urlencode({
                "client_id": settings["client_id"],
                "client_secret": settings["client_secret"],
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(token_request, timeout=30) as response:
            access_token = json.load(response)["access_token"]

        safe_details = asdict(scraped)
        safe_details.pop("account_id", None)
        body = (
            "Doctor identification failed in the RPA workflow.\n\n"
            f"Input: {json.dumps(safe_details, indent=2)}\n\nReason: {reason}"
        )
        mail_request = Request(
            f"https://graph.microsoft.com/v1.0/users/{quote(settings['sender'])}/sendMail",
            data=json.dumps({
                "message": {
                    "subject": "RPA doctor identification requires review",
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": recipient}}],
                },
                "saveToSentItems": True,
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(mail_request, timeout=30) as response:
            if response.status != 202:
                raise RuntimeError(f"Microsoft Graph sendMail returned {response.status}")


class DoctorMatchService:
    """Resolve one scraped doctor without ever selecting an ambiguous record."""

    FIELD_ALIASES = {
        "account_id": ("account_id", "AccountId", "id"),
        "doctor_id": ("doctor_id", "DoctorId", "Id"),
        "name": ("name", "AccountName", "DoctorName", "doctor", "prescriber"),
        "email": ("email", "Email", "mail"),
        "phone": ("phone", "Phone", "PhoneNumber", "telephone"),
        "address": ("address", "Address", "DoctorAddress"),
        "zip_code": ("zip_code", "ZipCode", "Zip", "PostalCode", "postalCode"),
        "practice": ("practice", "PracticeName", "clinic", "laboratory"),
    }

    def __init__(
        self,
        name_threshold: int = 85,
        address_threshold: int = 85,
        ambiguity_margin: float = 3.0,
        notifier: MatchNotifier | None = None,
    ) -> None:
        self.name_threshold = name_threshold
        self.address_threshold = address_threshold
        self.ambiguity_margin = ambiguity_margin
        self.notifier = notifier

    def identify(
        self,
        scraped: DoctorIdentity | Mapping[str, Any],
        records: Iterable[Any],
    ) -> DoctorMatch:
        source = self._coerce(scraped)
        candidates = [self._coerce(record) for record in records]
        candidates = [
            candidate for candidate in candidates
            if candidate.doctor_id or candidate.account_id
        ]
        if not any((source.name, source.email, source.phone, source.address, source.practice)):
            raise DoctorIdentificationError("No doctor identity fields were scraped")
        if not candidates:
            raise DoctorIdentificationError("The database returned no usable doctor records")

        strict = [candidate for candidate in candidates if self._strict(source, candidate)]
        if len(strict) == 1:
            return DoctorMatch(strict[0], "strict", 100.0, self._scores(source, strict[0]))

        # An email or phone can legitimately be shared by several doctors at one
        # practice. Rank those strict candidates using the remaining fields.
        pool = strict if strict else candidates

        ranked: list[tuple[float, DoctorIdentity, Mapping[str, float]]] = []
        for candidate in pool:
            scores = self._scores(source, candidate)
            if source.name and scores["name"] < self.name_threshold:
                continue
            if source.address and candidate.address and scores["address"] < self.address_threshold:
                continue
            weights = {
                "email": 30, "phone": 20, "name": 30, "address": 10,
                "zip_code": 10, "practice": 20,
            }
            # Missing database values are evidence, too: do not let a name-only
            # row tie a row that also matches the scraped practice/address.
            available = [field for field in weights if getattr(source, field)]
            if not available:
                continue
            confidence = sum(scores[field] * weights[field] for field in available) / sum(
                weights[field] for field in available
            )
            ranked.append((confidence, candidate, scores))

        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            raise DoctorIdentificationError(
                f"No candidate met name/address thresholds ({self.name_threshold}%/{self.address_threshold}%)"
            )
        best = ranked[0]
        if len(ranked) > 1 and best[0] - ranked[1][0] < self.ambiguity_margin:
            raise DoctorIdentificationError(
                "Fuzzy matching is ambiguous: top candidates score "
                f"{best[0]:.1f}% and {ranked[1][0]:.1f}%"
            )
        return DoctorMatch(best[1], "fuzzy", round(best[0], 2), best[2])

    def identify_or_notify(
        self,
        scraped: DoctorIdentity | Mapping[str, Any],
        records: Iterable[Any],
    ) -> DoctorMatch:
        source = self._coerce(scraped)
        try:
            return self.identify(source, records)
        except DoctorIdentificationError as error:
            if self.notifier is not None:
                try:
                    self.notifier.send(source, str(error))
                except Exception as notification_error:
                    raise DoctorIdentificationError(
                        f"{error}; administrator notification failed: {notification_error}"
                    ) from error
            raise

    def _strict(self, source: DoctorIdentity, candidate: DoctorIdentity) -> bool:
        fields = ("email", "phone", "name", "address", "practice")
        comparable = [
            field for field in fields
            if getattr(source, field) and getattr(candidate, field)
        ]
        if not comparable:
            return False
        # Email/phone independently identify a record. Otherwise all available
        # descriptive fields must match exactly.
        if source.email and candidate.email and self._email(source.email) == self._email(candidate.email):
            return True
        if source.phone and candidate.phone and self._phone(source.phone) == self._phone(candidate.phone):
            return True
        return all(
            self._text(getattr(source, field)) == self._text(getattr(candidate, field))
            for field in comparable
        )

    def _scores(self, source: DoctorIdentity, candidate: DoctorIdentity) -> dict[str, float]:
        source_zip = source.zip_code or self._zip_from_address(source.address)
        candidate_zip = candidate.zip_code or self._zip_from_address(candidate.address)
        return {
            "email": float(fuzz.ratio(self._email(source.email), self._email(candidate.email))) if source.email else 0.0,
            "phone": 100.0 if source.phone and self._phone(source.phone) == self._phone(candidate.phone) else 0.0,
            "name": self._name_score(source.name, candidate.name),
            "address": float(fuzz.token_set_ratio(self._text(source.address), self._text(candidate.address))) if source.address else 0.0,
            "zip_code": 100.0 if source_zip and source_zip == candidate_zip else 0.0,
            "practice": float(fuzz.token_set_ratio(
                self._text(source.practice), self._text(candidate.practice)
            )) if source.practice else 0.0,
        }

    @classmethod
    def _name_score(cls, left: str, right: str) -> float:
        """Recognize a first initial without equating different full names.

        Keep this in ranking, not the strict shortcut, so duplicate abbreviated
        names still require contact/address/practice evidence or remain ambiguous.
        Require the complete surname token sequence to agree; middle-name
        differences are deliberately left to the existing fuzzy scorer.
        """
        left_name, right_name = cls._text(left), cls._text(right)
        left_parts, right_parts = left_name.split(), right_name.split()
        if (
            len(left_parts) >= 2 and len(right_parts) >= 2
            and left_parts[1:] == right_parts[1:]
            and left_parts[0][0] == right_parts[0][0]
            and left_parts[0].isalpha() and right_parts[0].isalpha()
            and (len(left_parts[0]) == 1 or len(right_parts[0]) == 1)
        ):
            return 100.0
        return float(fuzz.token_sort_ratio(left_name, right_name)) if left_name else 0.0

    @classmethod
    def _coerce(cls, value: Any) -> DoctorIdentity:
        if isinstance(value, DoctorIdentity):
            return value
        if is_dataclass(value):
            data = asdict(value)
        elif isinstance(value, Mapping):
            data = value
        elif hasattr(value, "to_dict"):  # pandas.Series
            data = value.to_dict()
        else:
            data = vars(value)
        return DoctorIdentity(**{
            field: str(next((data[key] for key in aliases if data.get(key) is not None), "") or "").strip()
            for field, aliases in cls.FIELD_ALIASES.items()
        })

    @staticmethod
    def _text(value: str) -> str:
        value = re.sub(r"\([^)]*\)\s*$", "", value or "")
        value = re.sub(r"^(?:dr|doctor)\.?\s+", "", value, flags=re.IGNORECASE)
        return " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())

    @staticmethod
    def _email(value: str) -> str:
        return "".join((value or "").casefold().split())

    @staticmethod
    def _phone(value: str) -> str:
        digits = re.sub(r"\D", "", value or "")
        return digits[-10:] if len(digits) >= 10 else digits

    @staticmethod
    def _zip_from_address(value: str) -> str:
        match = re.search(r"\b(\d{5})(?:-\d{4})?\b", value or "")
        return match.group(1) if match else ""
