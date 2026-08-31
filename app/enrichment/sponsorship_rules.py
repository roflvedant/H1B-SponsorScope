"""
Reusable sponsorship-language rules.

Purpose
-------
These rules identify explicit sponsorship statements inside individual job
descriptions. They are occupation-independent and can therefore classify data,
software, mechanical, financial, healthcare, and other positions.

Design Principles
-----------------
1. Only classify explicit evidence from the current posting.
2. Avoid assuming that a company sponsors merely because it has sponsored
   workers historically.
3. Prefer UNKNOWN when the description contains no conclusive statement.
4. Treat required U.S. citizenship and required active government clearances
   as unavailable for the F-1/H-1B audience.
5. Preserve H-1B transfer support separately from new sponsorship.
6. Use reusable grammatical patterns rather than company-specific rules.

Important
---------
These patterns should never contain logic such as:

    if company == "Anthropic"

The wording—not the employer name—determines the current-posting policy.
"""

# =============================================================================
# Classifier Version
# =============================================================================

# Increment this whenever classification behavior changes materially.
#
# The version is stored in PostgreSQL with every classification, allowing us to
# compare results from earlier and later classifier versions without losing
# traceability.
CLASSIFIER_VERSION = "rules-v4"


# =============================================================================
# Explicit Positive Sponsorship Rules
# =============================================================================

POSITIVE_RULES = {
    # Matches:
    #   "Visa sponsorship is available."
    #   "Employment sponsorship may be available for eligible applicants."
    #
    # This rule requires a positive availability statement. Merely mentioning
    # "visa sponsorship" is not sufficient.
    "SPONSORSHIP_AVAILABLE": (
        r"\b(?:visa|immigration|employment|work authorization)?\s*"
        r"sponsorship\s+"
        r"(?:is|may be|will be)\s+available\b"
    ),

    # Matches the language found in several Capital One postings:
    #   "Capital One will consider sponsoring a new qualified applicant."
    #
    # "Consider sponsoring" is not an absolute guarantee, but it explicitly
    # establishes that sponsorship is possible for a qualified applicant.
    "WILL_CONSIDER_SPONSORING": (
        r"\b(?:we|the company|[a-z0-9&.' -]+)?\s*"
        r"(?:will|may)\s+consider\s+sponsoring\s+"
        r"(?:a\s+)?(?:new\s+)?(?:qualified\s+)?applicant\b"
    ),

    # Matches:
    #   "We do sponsor visas."
    #   "The company sponsors employment visas."
    #
    # Requiring an affirmative verb prevents generic phrases such as
    # "visa sponsorship policy" from becoming positive evidence.
    "COMPANY_SPONSORS_VISAS": (
        r"\b(?:we|the company|this employer)\s+"
        r"(?:do\s+)?sponsor(?:s)?\s+"
        r"(?:employment\s+|work\s+)?visas?\b"
    ),

    # Matches:
    #   "Sponsorship will be provided for the successful candidate."
    #
    # This captures explicit commitments that use "provided" instead of
    # "available."
    "SPONSORSHIP_PROVIDED": (
        r"\bsponsorship\s+"
        r"(?:will|can)\s+be\s+provided\b"
    ),

    # Matches:
    #   "Applicants requiring visa sponsorship are welcome to apply."
    #
    # This is explicit positive evidence because the posting directly invites
    # candidates who require sponsorship.
    "SPONSORSHIP_CANDIDATES_WELCOME": (
        r"\b(?:applicants?|candidates?)\s+"
        r"(?:who\s+)?requir(?:e|ing)\s+"
        r"(?:visa\s+|employment\s+)?sponsorship\s+"
        r"(?:are\s+)?(?:welcome|encouraged)\s+to\s+apply\b"
    ),
}


# =============================================================================
# Explicit Negative Sponsorship Rules
# =============================================================================

NEGATIVE_RULES = {
        # Matches direct sponsorship refusals, including:
    #
    #   "We do not sponsor applicants."
    #   "UPMC does not offer any type of sponsorship."
    #   "This position does not offer employer-based visa sponsorship."
    #
    # Several optional phrases are included because employers often insert
    # words such as "any type of" between the refusal and "sponsorship."
    
    "SPONSORSHIP_REFUSED": (
        r"\b"
        r"(?:we|the company|this employer|the business|"
        r"[a-z0-9&.' -]+)?\s*"
        r"(?:"
        r"do(?:es)?\s+not|"
        r"will\s+not|"
        r"cannot|"
        r"can't|"
        r"is\s+unable\s+to|"
        r"are\s+unable\s+to|"
        r"unable\s+to|"
        r"not\s+able\s+to"
        r")\s+"
        r"(?:provide\s+|offer\s+)?"
        r"(?:any\s+)?"
        r"(?:type\s+of\s+)?"
        r"(?:new\s+)?"
        r"(?:"
        r"visa\s+|"
        r"employment(?:-based)?\s+|"
        r"employer(?:-based)?\s+(?:visa\s+)?|"
        r"immigration(?:-related)?\s+"
        r")?"
        r"sponsor(?:ship|ing|s)?\b"
    ),

    # Matches:
    #   "Visa sponsorship is not available for this position."
    #   "Employment sponsorship will not be available."
    #
    # This handles passive constructions that do not use "we cannot."
    "SPONSORSHIP_NOT_AVAILABLE": (
        r"\b(?:visa|employment|work authorization|immigration)?\s*"
        r"sponsorship\s+"
        r"(?:is|will be)\s+not\s+available\b"
    ),

    # Matches:
    #   "No sponsorship available."
    #   "No visa sponsorship is available."
    "NO_SPONSORSHIP_AVAILABLE": (
        r"\bno\s+"
        r"(?:visa\s+|employment\s+)?"
        r"sponsorship\s+"
        r"(?:is\s+)?available\b"
    ),

    # Matches:
    #
    #   "This role is not eligible for visa sponsorship."
    #   "This role is not eligible for Mastercard's work authorization
    #    sponsorship."
    #
    # Some job descriptions insert the employer's possessive name before
    # "work authorization sponsorship." The optional possessive phrase allows
    # that variation without hardcoding Mastercard or another company.
    "ROLE_NOT_ELIGIBLE": (
        r"\b(?:this\s+)?"
        r"(?:role|position|job)\s+"
        r"is\s+not\s+eligible\s+for\s+"
        r"(?:[a-z0-9&.' -]+['’]s\s+)?"
        r"(?:"
        r"visa\s+|"
        r"employment\s+|"
        r"work\s+authorization\s+"
        r")?"
        r"sponsorship\b"
    ),

    # Matches:
    #   "Applicants must be authorized without employer sponsorship."
    #   "Must work without current or future sponsorship."
    #
    # Generic "authorized to work" language alone stays UNKNOWN. The decisive
    # part is the explicit "without sponsorship" restriction.
    "AUTHORIZATION_WITHOUT_SPONSORSHIP": (
        r"\b(?:authorized|authorization|eligible)\s+"
        r"(?:to\s+work\s+)?"
        r"(?:in\s+the\s+(?:u\.?s\.?|united states)\s+)?"
        r"(?:now\s+and\s+in\s+the\s+future\s+)?"
        r"without\s+"
        r"(?:current\s+or\s+future\s+|"
        r"now\s+or\s+in\s+the\s+future\s+|"
        r"employer\s+)?"
        r"sponsorship\b"
    ),

    # Matches a frequent alternative construction:
    #   "Work authorization must not require sponsorship now or in the future."
    "MUST_NOT_REQUIRE_SPONSORSHIP": (
        r"\b(?:work\s+authorization|applicants?|candidates?)"
        r".{0,100}?"
        r"(?:must\s+not|does\s+not|do\s+not)\s+"
        r"(?:now\s+or\s+in\s+the\s+future\s+)?"
        r"require\s+"
        r"(?:employer\s+|visa\s+)?sponsorship\b"
    ),

    # Matches:
    #   "The company will not provide immigration-related support."
    #   "No immigration support is available for this role."
    #
    # Some employers avoid the word "sponsorship" and instead describe the
    # same restriction as immigration support.
    "NO_IMMIGRATION_SUPPORT": (
        r"\b(?:will\s+not|does\s+not|do\s+not|cannot|unable\s+to|no)\s+"
        r"(?:provide\s+|offer\s+)?"
        r"(?:any\s+)?"
        r"immigration(?:-related)?\s+support\b"
    ),

    # Matches:
    #   "The company does not support H-1B petitions."
    #   "We do not sponsor/support H-1B, TN, or STEM OPT."
    "H1B_SUPPORT_REFUSED": (
        r"\b(?:do(?:es)?\s+not|will\s+not|cannot)\s+"
        r"(?:sponsor(?:/support)?|support)\s+"
        r"(?:new\s+)?h-?1b(?:\s+petitions?)?\b"
    ),

    # Matches restrictions that explicitly include F-1 programs:
    #   "No sponsorship or support for F-1 OPT or STEM OPT."
    #   "The company does not participate in the STEM OPT extension."
    #
    # This is especially important for the product's international-student
    # audience even when H-1B is not mentioned.
    "OPT_SUPPORT_REFUSED": (
        r"\b(?:do(?:es)?\s+not|will\s+not|cannot|no)\s+"
        r"(?:provide\s+|offer\s+|participate\s+in\s+)?"
        r"(?:any\s+)?"
        r"(?:support\s+for\s+)?"
        r"(?:f-?1\s+)?(?:stem\s+)?opt"
        r"(?:\s+extension|\s+support|\s+sponsorship)?\b"
    ),

    # Matches:
    #   "Only U.S. citizens or green-card holders will be considered."
    #   "Visa: GC and USC only."
    #
    # These statements exclude candidates who need employment sponsorship even
    # if the posting never uses the word "sponsor."
    "CITIZEN_OR_GREEN_CARD_ONLY": (
        r"\b(?:only\s+)?"
        r"(?:u\.?s\.?\s+citizens?|usc)"
        r"\s+(?:or|and)\s+"
        r"(?:current\s+)?(?:green[- ]card holders?|gc)"
        r"(?:\s+only|\s+will be considered)?\b"
        r"|"
        r"\bvisa\s*:\s*(?:gc|green[- ]card)"
        r"\s+(?:and|or)\s+(?:usc|u\.?s\.?\s+citizens?)"
        r"\s+only\b"
    ),

    # Matches explicit citizenship requirements:
    #
    #   "This position requires U.S. citizenship."
    #   "The role may be remote, requiring U.S. citizenship."
    #   "Candidates must be U.S. citizens."
    #   "U.S. citizenship is required."
    #
    # This deliberately does not match equal-opportunity language such as:
    #
    #   "We do not discriminate based on citizenship status."
    #
    # The rule requires an obligation word such as requires, requiring, must,
    # or required.
    "US_CITIZENSHIP_REQUIRED": (
        r"\b(?:"
        r"(?:this\s+)?(?:position|role|job)\s+"
        r"(?:requires?|requiring)\s+"
        r"(?:u\.?s\.?|united\s+states)\s+citizenship"
        r"|"
        r"(?:requires?|requiring)\s+"
        r"(?:u\.?s\.?|united\s+states)\s+citizenship"
        r"|"
        r"(?:applicants?|candidates?|employees?)\s+"
        r"must\s+be\s+"
        r"(?:a\s+)?(?:u\.?s\.?|united\s+states)\s+citizens?"
        r"|"
        r"must\s+be\s+"
        r"(?:a\s+)?(?:u\.?s\.?|united\s+states)\s+citizens?"
        r"|"
        r"(?:u\.?s\.?|united\s+states)\s+citizenship\s+"
        r"(?:is\s+)?"
        r"(?:required|(?:a\s+)?(?:strict\s+)?(?:minimum\s+)?requirement)"
        r"|"
        r"citizenship\s+"
        r"(?:is\s+)?required"
        r")\b"
    ),

        # -------------------------------------------------------------------------
    # Existing government clearance required
    # -------------------------------------------------------------------------
    #
    # Matches postings requiring the applicant to already possess a security
    # clearance, including:
    #
    #   "Active Top Secret security clearance."
    #   "Hold an active TS/SCI security clearance."
    #   "Current TS/SCI clearance is required."
    #   "Candidates should have an active security clearance."
    #   "Active Secret Clearance or current interim."
    #   "Security Clearance Is Required — Currently Have Security Clearance."
    #
    # Why this is treated as unavailable
    # -----------------------------------
    # An active U.S. government clearance generally cannot be supplied through
    # ordinary employment sponsorship. For this F-1-focused product, an
    # already-active clearance requirement excludes the intended user group.
    #
    # Precision safeguard
    # -------------------
    # This rule does not match:
    #
    #   "Ability to obtain a clearance."
    #   "Active clearance is a strong plus."
    #   "Clearance preferred."
    #
    # Those statements do not necessarily require the applicant to possess an
    # active clearance when applying.
    "ACTIVE_CLEARANCE_REQUIRED": (
        r"\b(?:"

        # Examples:
        #   "must hold an active TS/SCI clearance"
        #   "must have an active Secret clearance"
        #   "requires an active Top Secret security clearance"
        r"(?:must\s+(?:hold|have|possess)|requires?)\s+"
        r"(?:an?\s+)?active\s+"
        r"(?:(?:secret|top\s+secret|ts/?sci|q)\s+)?"
        r"(?:security\s+)?clearance"

        r"|"

        # Examples:
        #   "hold an active TS/SCI security clearance"
        #   "have an active security clearance"
        #
        # Some qualification lists omit "must" while still using a command-like
        # requirement. The active-clearance phrase remains explicit.
        r"(?:hold|have|possess)\s+"
        r"(?:an?\s+)?active\s+"
        r"(?:(?:secret|top\s+secret|ts/?sci|q)\s+)?"
        r"(?:security\s+)?clearance"

        r"|"

        # Examples:
        #   "Active Top Secret security clearance."
        #   "Active security clearance with polygraph."
        #
        # A standalone bullet in the qualifications section may not include
        # "required," but explicitly naming an active clearance functions as a
        # qualification. "Strong plus" is excluded below using a negative
        # lookahead.
        r"active\s+"
        r"(?:(?:secret|top\s+secret|ts/?sci|q)\s+)?"
        r"(?:security\s+)?clearance"
        r"(?!\s+(?:is\s+)?(?:preferred|a\s+strong\s+plus|a\s+plus))"

        r"|"

        # Examples:
        #   "Current TS/SCI clearance is required."
        #   "Current security clearance required."
        r"current\s+"
        r"(?:(?:secret|top\s+secret|ts/?sci|q)\s+)?"
        r"(?:security\s+)?clearance"
        r".{0,50}?"
        r"(?:is\s+)?required"

        r"|"

        # Example:
        #   "Clearance: Current TS/SCI Clearance with active or ability to
        #    obtain CI Polygraph is required."
        #
        # The existing TS/SCI clearance applies now; only the polygraph may be
        # obtained later.
        r"clearance\s*:\s*current\s+"
        r"(?:(?:secret|top\s+secret|ts/?sci|q)\s+)?"
        r"(?:security\s+)?clearance"
        r".{0,100}?"
        r"(?:is\s+)?required"

        r"|"

        # Examples:
        #   "Candidates should have an active security clearance."
        #   "Applicants are required to have an active clearance."
        r"(?:applicants?|candidates?)\s+"
        r"(?:should|must|are\s+required\s+to)\s+"
        r"(?:have|hold|possess)\s+"
        r"(?:an?\s+)?active\s+"
        r"(?:(?:secret|top\s+secret|ts/?sci|q)\s+)?"
        r"(?:security\s+)?clearance"

        r"|"

        # Example:
        #   "Security Clearance Is Required — Currently Have Security
        #    Clearance."
        r"(?:security\s+)?clearance\s+"
        r"(?:is\s+)?required"
        r".{0,80}?"
        r"currently\s+(?:have|hold|possess)\s+"
        r"(?:a\s+)?(?:security\s+)?clearance"

        r")\b"
    ),

    # Matches roles requiring the candidate to already possess a clearance:
    #
    #   "Candidates must currently have security clearance."
    #   "Current security clearance is required."
    #   "Applicants must currently hold a Secret clearance."
    #
    # This differs from:
    #
    #   "Must be able to obtain a clearance."
    #
    # The latter does not necessarily mean the candidate must already possess
    # one, so it should not be matched by this specific rule.
    "CURRENT_CLEARANCE_REQUIRED": (
        r"\b(?:"
        r"(?:applicants?|candidates?)\s+"
        r"must\s+currently\s+"
        r"(?:have|hold|possess)\s+"
        r"(?:an?\s+)?"
        r"(?:(?:secret|top\s+secret|ts/?sci)\s+)?"
        r"(?:security\s+)?clearance"
        r"|"
        r"must\s+currently\s+"
        r"(?:have|hold|possess)\s+"
        r"(?:an?\s+)?"
        r"(?:(?:secret|top\s+secret|ts/?sci)\s+)?"
        r"(?:security\s+)?clearance"
        r"|"
        r"current\s+"
        r"(?:(?:secret|top\s+secret|ts/?sci)\s+)?"
        r"(?:security\s+)?clearance\s+"
        r"(?:is\s+)?required"
        r"|"
        r"(?:applicants?|candidates?)\s+"
        r"who\s+do\s+not\s+currently\s+hold\s+"
        r"the\s+required\s+clearance"
        r".{0,60}?"
        r"(?:are\s+)?not\s+eligible"
        r")\b"
    ),

    # -------------------------------------------------------------------------
    # H-1B lottery hiring restriction
    # -------------------------------------------------------------------------
    #
    # Matches wording such as:
    #
    #   "Does not intend to hire job seekers who will need, now or in the
    #    future, sponsorship through the H-1B lottery."
    #
    # The posting may link to a limited exception policy. For the general
    # applicant population, the posting is still explicitly restrictive.
    # Exact exceptions should eventually be represented as structured metadata,
    # but they should not cause the restriction to remain UNKNOWN.
    "H1B_LOTTERY_RESTRICTION": (
        r"\b(?:do(?:es)?\s+not|will\s+not)\s+"
        r"(?:intend\s+to\s+)?hire\s+"
        r"(?:experienced\s+or\s+entry[- ]level\s+)?"
        r"(?:job\s+seekers?|applicants?|candidates?)\s+"
        r"who\s+(?:will\s+)?need"
        r".{0,80}?"
        r"(?:now\s+or\s+in\s+the\s+future)"
        r".{0,80}?"
        r"sponsorship\s+through\s+the\s+h-?1b\s+lottery\b"
    ),

    # -------------------------------------------------------------------------
    # Employer-sponsored work authorization refusal
    # -------------------------------------------------------------------------
    #
    # Matches:
    #
    #   "This role does not qualify for employer-sponsored work authorization."
    #
    # This differs grammatically from "we do not sponsor," but communicates the
    # same current-role restriction.
    "EMPLOYER_SPONSORED_AUTHORIZATION_UNAVAILABLE": (
        r"\b(?:this\s+)?(?:role|position|job)\s+"
        r"(?:does\s+not|will\s+not)\s+qualify\s+for\s+"
        r"employer[- ]sponsored\s+"
        r"(?:work|employment)\s+authorization\b"
    ),

}


# =============================================================================
# H-1B Transfer Rules
# =============================================================================

# H-1B transfers are stored separately because a posting may simultaneously:
#
#   - reject new H-1B petitions;
#   - accept candidates who already hold H-1B status.
#
# In that situation, the top-level current policy remains UNAVAILABLE for new
# sponsorship, while h1b_transfer_supported becomes True.
TRANSFER_RULES = {
    "H1B_TRANSFER_SUPPORTED": (
        r"\bh-?1b\s+transfer\s+"
        r"(?:candidates?|applicants?)\s+"
        r"(?:are\s+)?"
        r"(?:welcome|encouraged|accepted)\b"
    ),

    "H1B_TRANSFER_AVAILABLE": (
        r"\b(?:we|the company)\s+"
        r"(?:can|will|may)\s+"
        r"(?:support|accept|process)\s+"
        r"(?:an?\s+)?h-?1b\s+transfer\b"
    ),
}


