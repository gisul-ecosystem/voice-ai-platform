"""Belief Judge: Evaluate answer credibility to guide follow-up decisions (Phase 4).

The Belief Judge assesses whether candidate answers are believable, questionable,
or likely fabricated based on specific patterns and inconsistencies. This influences
whether the interviewer should accept claims at face value or probe deeper for verification.
"""
from __future__ import annotations

import re
from typing import Any

# Patterns that suggest potential fabrication or exaggeration
CREDIBILITY_PATTERNS = {
    "vague_ownership": [
        r"\bour team\b",
        r"\bwe (decided|built|implemented)\b", 
        r"\bthe team (handled|managed)\b",
        r"\bi was (involved|part of)\b",
        r"\bi helped (with|build)\b",
    ],
    "unrealistic_scale": [
        r"\b(millions|billions) of (users|requests|records)\b",
        r"\b(100%|zero) (uptime|downtime|latency)\b",
        r"\b(eliminated|reduced).* 100%\b",
        r"\binfinite scalability\b",
        r"\bnever (fails|crashes|goes down)\b",
    ],
    "buzzword_heavy": [
        r"\b(ai|ml|blockchain|microservices|kubernetes|docker|aws|cloud-native|serverless|devops|agile|scrum).{0,20}\b(ai|ml|blockchain|microservices|kubernetes|docker|aws|cloud-native|serverless|devops|agile|scrum)\b",
        r"\b(cutting.edge|state.of.the.art|revolutionary|game.changing|paradigm.shifting)\b",
        r"\b(enterprise|scalable|robust|performant|optimized).{0,20}\b(enterprise|scalable|robust|performant|optimized)\b",
    ],
    "missing_context": [
        r"\bi (built|designed|implemented) the (system|platform|solution)$",
        r"\bwe used (redis|postgres|kafka|kubernetes)$",
        r"\bit was (fast|scalable|reliable)$",
        r"\bthe (algorithm|approach|pattern) was (good|efficient|optimal)$",
    ],
    "textbook_parroting": [
        r"\b(time complexity|space complexity|big o notation)\b.{0,50}\bO\([^)]+\)",
        r"\b(solid principles|design patterns|mvc pattern)\b.{0,50}\b(single responsibility|open.closed|dependency inversion)\b",
        r"\b(cap theorem|acid properties|base properties)\b.{0,50}\b(consistency|availability|partition tolerance)\b",
        r"\bdefinition of\b",
        r"\baccording to\b",
        r"\bin computer science\b",
    ],
    "contradictory_claims": [
        r"\bbut (actually|really|in fact)\b",
        r"\b(however|although).{10,50}\b(but|however)\b",
        r"\bi (said|meant|intended)\b.{10,50}\b(not|didn't|wasn't)\b",
    ],
    "impossible_combinations": [
        r"\b(nosql|mongodb).{0,30}\b(acid|transactions|joins)\b",
        r"\b(stateless).{0,30}\b(session|state|memory)\b",
        r"\b(microservices).{0,30}\b(monolithic|single database)\b",
    ],
    "overly_perfect": [
        r"\b(never had|zero|no) (bugs|issues|problems|downtime|errors)\b",
        r"\b(first try|immediately) (worked|succeeded|solved)\b",
        r"\b(perfect|flawless|seamless) (implementation|integration|deployment)\b",
    ],
}

# Positive credibility signals (increase believability)
CREDIBILITY_BOOSTERS = {
    "specific_numbers": [
        r"\b\d+(\.\d+)?\s*(ms|seconds?|minutes?|hours?|days?)\b",
        r"\b\d+(\.\d+)?\s*(mb|gb|tb|requests?|users?|rows?|records?)\b", 
        r"\b\d+(\.\d+)?\s*(%|percent|times faster|x improvement)\b",
    ],
    "concrete_context": [
        r"\b(at|when|during) (my previous job|that company|the startup)\b",
        r"\b(the client|my manager|the team lead) (asked|wanted|decided)\b",
        r"\b(q[1-4]|january|february|march|april|may|june|july|august|september|october|november|december) \d{4}\b",
    ],
    "personal_ownership": [
        r"\bi (personally|directly|individually) (built|wrote|designed|implemented)\b",
        r"\bi was (responsible|accountable) for\b",
        r"\bmy (decision|choice|implementation) was\b",
        r"\bi (chose|decided|picked) (to|because)\b",
    ],
    "failure_admission": [
        r"\b(mistake|error|bug|issue) (i|we) (made|caused|introduced)\b",
        r"\b(didn't work|failed|broke) (initially|at first)\b",
        r"\b(learned|realized) (that|from|after)\b",
        r"\bhad to (refactor|rewrite|fix|debug)\b",
    ],
    "technical_constraints": [
        r"\bbecause of (memory|cpu|latency|bandwidth|budget) (constraints?|limits?)\b",
        r"\b(couldn't|can't) (use|do|implement) .{5,30} because\b",
        r"\btrade.?off (was|is) .{5,30} (vs|versus|against)\b",
    ],
}

def evaluate_credibility(
    answer: str, 
    *,
    previous_facts: list[str] | None = None,
    competency_context: str | None = None
) -> tuple[str, list[str]]:
    """Phase 4: Evaluate answer credibility and return assessment + signals.
    
    Returns:
        tuple: (credibility_assessment, credibility_signals)
        - credibility_assessment: "believable" | "questionable" | "likely_fabricated"  
        - credibility_signals: list of specific patterns detected
    """
    if not answer or len(answer.strip()) < 10:
        return "believable", []
    
    text = answer.lower()
    signals = []
    negative_score = 0
    positive_score = 0
    
    # Check for negative credibility patterns
    for pattern_type, regexes in CREDIBILITY_PATTERNS.items():
        for regex in regexes:
            if re.search(regex, text, re.IGNORECASE):
                signals.append(pattern_type)
                negative_score += 1
                break  # Only count each pattern type once
    
    # Check for positive credibility boosters  
    booster_signals = []
    for pattern_type, regexes in CREDIBILITY_BOOSTERS.items():
        for regex in regexes:
            if re.search(regex, text, re.IGNORECASE):
                booster_signals.append(f"has_{pattern_type}")
                positive_score += 1
                break  # Only count each pattern type once
    
    # Check for contradictions with previous facts
    if previous_facts:
        contradictions = _check_fact_contradictions(text, previous_facts)
        if contradictions:
            signals.extend(contradictions)
            negative_score += len(contradictions)
    
    # Determine overall credibility assessment
    net_score = positive_score - negative_score
    
    if negative_score >= 3 or any(sig in signals for sig in ["impossible_combinations", "contradictory_claims"]):
        assessment = "likely_fabricated"
    elif negative_score >= 1 or net_score <= -1:
        assessment = "questionable"  
    else:
        assessment = "believable"
    
    # Include booster signals in final signal list
    all_signals = signals + booster_signals
    
    return assessment, all_signals[:10]  # Limit to 10 signals


def _check_fact_contradictions(text: str, previous_facts: list[str]) -> list[str]:
    """Check if current answer contradicts previously established facts."""
    contradictions = []
    
    # Simple heuristic: look for negations of previous claims
    for fact in previous_facts:
        if len(fact) < 10:
            continue
        
        # Extract key terms from the fact
        key_terms = re.findall(r'\b\w{4,}\b', fact.lower())
        if not key_terms:
            continue
            
        # Look for negations of those terms in current text
        for term in key_terms[:3]:  # Check up to 3 key terms
            negation_patterns = [
                rf"\b(not|never|didn't|wasn't|isn't|can't|couldn't|wouldn't)\b.{{0,20}}\b{re.escape(term)}\b",
                rf"\b{re.escape(term)}.{{0,20}}\b(not|never|didn't|wasn't|isn't|can't|couldn't|wouldn't)\b",
            ]
            for pattern in negation_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    contradictions.append(f"contradicts_fact_{term}")
                    break
    
    return contradictions


def should_probe_deeper(
    credibility_assessment: str, 
    credibility_signals: list[str],
    technical_substance: str = "partial"
) -> bool:
    """Phase 4: Determine if interviewer should probe deeper based on credibility."""
    
    # Always probe likely fabricated answers
    if credibility_assessment == "likely_fabricated":
        return True
    
    # Probe questionable answers unless they have deep technical substance
    if credibility_assessment == "questionable":
        return technical_substance != "deep"
    
    # Don't probe believable answers with deep substance
    if credibility_assessment == "believable" and technical_substance == "deep":
        return False
    
    # Check for specific signals that warrant probing
    probe_worthy_signals = {
        "vague_ownership", "unrealistic_scale", "missing_context", 
        "textbook_parroting", "overly_perfect"
    }
    
    return any(signal in probe_worthy_signals for signal in credibility_signals)