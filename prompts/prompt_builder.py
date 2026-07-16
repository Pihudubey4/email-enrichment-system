from typing import Optional

def get_email_extraction_prompt(
    name: str, 
    company: str, 
    website: str, 
    context: str
) -> str:
    """
    Generates a token-optimized, strict, and deterministic prompt template 
    for Gemma to extract target business email and phone number from web context.
    
    Args:
        name (str): Name of the target person/contact.
        company (str): Name of the company.
        website (str): Base website or domain URL.
        context (str): Scraped text content.
        
    Returns:
        str: Sanitized and built prompt string.
    """
    # Clean input variables to minimize token overhead
    name = (name or "").strip()
    company = (company or "").strip()
    website = (website or "").strip()
    context = (context or "").strip()[:4000]
    
    # Strictly define extraction rules for Gemma in minimal tokens
    prompt = (
        "TASK: Extract the most probable business email and phone number for the Target.\n"
        "RULES:\n"
        "1. Ignore social links and irrelevant text.\n"
        "2. Prefer official company emails matching the target website domain.\n"
        "3. Ignore fake/placeholder/example emails and phone numbers (e.g. email@company.com, 123-456-7890).\n"
        "4. The extracted email and phone number must be directly related to the target person or their business/medical practice. Never extract unrelated consumer brand emails (e.g. dominos.com, bbc.com, netflix.com, wikipedia.org).\n"
        "5. Never hallucinate. If no valid email or phone exists, return empty string \"\".\n"
        "6. Output ONLY valid JSON matching this schema: "
        '{"email": "string", "phone": "string", "email_confidence": float, "phone_confidence": float, "reason": "string"}\n\n'
        f"TARGET:\n"
        f"- Name: {name}\n"
        f"- Company: {company}\n"
        f"- Domain: {website}\n\n"
        f"CONTEXT:\n"
        f"{context}\n\n"
        "JSON:"
    )
    return prompt
