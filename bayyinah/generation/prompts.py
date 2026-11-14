"""Prompts.

Deliberately short and rule-dense. Legal retrieval prompts get *worse* when you
add "be helpful", personality, or examples that drift from the corpus. The
rules below are all enforceable downstream, which is the point: a rule the
verifier cannot check is decoration.
"""

from __future__ import annotations

SYSTEM_AR = """\
أنت مساعد امتثال عمالي سعودي. مهمتك اختيار النصوص القانونية ونقلها، لا تأليفها.

قواعد صارمة:
1. استخدم فقط المقاطع المرقّمة المرفقة. لا تعتمد على أي معرفة خارجية.
2. كل عبارة قانونية يجب أن تُنسب إلى رقم المادة الذي وردت فيه، وتُنسخ حرفياً.
3. لا تحسب أي مبلغ أو مدة. إن وُجدت نتيجة أداة مرفقة فاستخدمها كما هي.
4. إذا لم تجد سنداً واضحاً، قل ذلك صراحةً ولا تخمّن.
5. أجب بنفس لغة السؤال.

أخرج كائن JSON فقط، بالمخطط المحدد، دون أي نص إضافي."""

JSON_CONTRACT = """\
{
  "answer": "نص الجواب بلغة السؤال",
  "citations": [
    {"doc_id": "معرف المستند", "article_no": "رقم المادة", "quote": "نص حرفي من المقطع"}
  ],
  "confidence": "high | medium | low",
  "refusal": null,
  "risk_flags": []
}"""


def build_user_prompt(question: str, chunks: list, *, problems: list[str] | None = None) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        blocks.append(
            f"[{i}] doc_id={c.doc_id} article_no={c.article_no}\n{c.text_display}"
        )
    context = "\n\n".join(blocks)

    repair = ""
    if problems:
        repair = (
            "\n\nمحاولتك السابقة رُفضت للأسباب التالية. صحّحها الآن دون اختلاق أي نص:\n"
            + "\n".join(f"- {p}" for p in problems)
        )

    return (
        f"المقاطع المتاحة:\n\n{context}\n\n"
        f"السؤال: {question}\n"
        f"{repair}\n"
        f"أخرج JSON بهذا المخطط فقط:\n{JSON_CONTRACT}"
    )


def build_contract_prompt(clause: str, chunks: list) -> str:
    blocks = "\n\n".join(f"[{i}] المادة {c.article_no}\n{c.text_display}" for i, c in enumerate(chunks, start=1))
    return (
        f"المقاطع النظامية:\n\n{blocks}\n\n"
        f"البند التعاقدي:\n{clause}\n\n"
        "هل يخالف البند النظام؟ أخرج JSON فقط:\n"
        '{"verdict":"compliant|risky|non_compliant|not_covered",'
        '"severity":"high|medium|low","article_no":"...","quote":"...",'
        '"rationale":"...","suggested_redline":"...","confidence":0.0}'
    )
