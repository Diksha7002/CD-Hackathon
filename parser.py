import re
from collections import namedtuple
from itertools import islice

MAX_CODE_LENGTH = 5000
MAX_IFS = 30
MAX_ITEMS_PER_BLOCK = 100
MAX_BLOCK_DEPTH = 20
TREE_LIMIT = 30
MAX_SHOWN = 4

KEYWORDS = {"if", "then", "else"}
BLOCK_SYMBOLS = {";", "{", "}"}

TOKEN_PATTERN = re.compile(
    r'"[^"\n]*"'
    r"|'[^'\n]*'"
    r"|[A-Za-z_]\w*"
    r"|\d+(?:\.\d+)?"
    r"|==|!=|<=|>=|&&|\|\|"
    r"|\S"
)

Token = namedtuple("Token", "text start end")


class ParseError(Exception):
    pass


def word(token):
    return token.text.lower()


def text_between(code, first, last):
    return code[first.start:last.end]


def tokenize(code):
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    code = re.sub(r"//[^\n]*|#[^\n]*", " ", code)
    tokens = [Token(m.group(), m.start(), m.end()) for m in TOKEN_PATTERN.finditer(code)]
    return code, tokens


def is_wrapped_in_parentheses(tokens, first, last):
    if tokens[first].text != "(" or tokens[last].text != ")":
        return False
    depth = 0
    for i in range(first, last + 1):
        if tokens[i].text == "(":
            depth += 1
        elif tokens[i].text == ")":
            depth -= 1
            if depth == 0 and i < last:
                return False
    return depth == 0


def find_then(tokens, start):
    for i in range(start, len(tokens)):
        token = tokens[i]
        if word(token) == "then":
            return i if i > start else None
        if word(token) in KEYWORDS or token.text in BLOCK_SYMBOLS:
            return None
    return None


def condition_before_then(code, tokens, first, then_pos):
    last = then_pos - 1
    if is_wrapped_in_parentheses(tokens, first, last):
        first, last = first + 1, last - 1
    if first > last:
        raise ParseError("The condition inside ( ) is empty.")
    return text_between(code, tokens[first], tokens[last]), then_pos


def parenthesized_condition(code, tokens, open_pos):
    depth = 0
    for i in range(open_pos, len(tokens)):
        if tokens[i].text == "(":
            depth += 1
        elif tokens[i].text == ")":
            depth -= 1
            if depth == 0:
                if i == open_pos + 1:
                    raise ParseError("The condition inside ( ) is empty.")
                return text_between(code, tokens[open_pos + 1], tokens[i - 1]), i + 1
    raise ParseError("Missing ')' - the condition of an 'if' is never closed.")


def single_word_condition(tokens, pos):
    token = tokens[pos]
    if token.text in BLOCK_SYMBOLS or word(token) in KEYWORDS:
        raise ParseError("'if' must be followed by a condition, for example: if (x > 0) ...")
    return token.text, pos + 1


def read_condition(code, tokens, pos):
    if pos >= len(tokens):
        raise ParseError("An 'if' at the end of the input has no condition.")
    then_pos = find_then(tokens, pos)
    if then_pos is not None:
        return condition_before_then(code, tokens, pos, then_pos)
    if tokens[pos].text == "(":
        return parenthesized_condition(code, tokens, pos)
    return single_word_condition(tokens, pos)


def read_simple_statement(code, tokens, start):
    pos = start
    while pos < len(tokens) and tokens[pos].text not in BLOCK_SYMBOLS and word(tokens[pos]) not in KEYWORDS:
        pos += 1
    if pos < len(tokens) and tokens[pos].text == ";":
        pos += 1
    return text_between(code, tokens[start], tokens[pos - 1]), pos


def build_items(code, tokens, pos, counters, depth):
    if depth > MAX_BLOCK_DEPTH:
        raise ParseError("Blocks { } are nested too deeply.")

    items = []
    while pos < len(tokens):
        token = tokens[pos]

        if token.text == "}":
            if depth == 0:
                raise ParseError("Found a '}' without a matching '{'.")
            return items, pos

        if token.text == "{":
            inner, closing_pos = build_items(code, tokens, pos + 1, counters, depth + 1)
            items.append({"kind": "block", "inner": inner})
            pos = closing_pos + 1

        elif word(token) == "if":
            counters["if"] += 1
            condition, pos = read_condition(code, tokens, pos + 1)
            if pos < len(tokens) and word(tokens[pos]) == "then":
                pos += 1
            items.append({"kind": "if", "id": counters["if"], "cond": condition})

        elif word(token) == "else":
            counters["else"] += 1
            items.append({"kind": "else", "id": counters["else"]})
            pos += 1

        elif word(token) == "then":
            raise ParseError("Unexpected 'then' - it must come right after the condition of an 'if'.")

        else:
            statement, pos = read_simple_statement(code, tokens, pos)
            items.append({"kind": "other", "text": statement})

    if depth > 0:
        raise ParseError("Missing '}' - a '{' block is never closed.")
    return items, pos


def count_kind(items, kind):
    return sum(1 for item in items if item["kind"] == kind)


def check_items(items):
    if len(items) > MAX_ITEMS_PER_BLOCK:
        raise ParseError("Too many statements in one block (limit: %d)." % MAX_ITEMS_PER_BLOCK)

    ifs = count_kind(items, "if")
    elses = count_kind(items, "else")
    if elses > ifs:
        raise ParseError(
            "There are more 'else' keywords (%d) than 'if' keywords (%d) at the same level, "
            "so some else has no if to belong to." % (elses, ifs))

    for index, item in enumerate(items):
        if item["kind"] == "else" and index == 0:
            raise ParseError("An 'else' cannot be the first thing here - there is no 'if' before it.")
        if item["kind"] == "if":
            following = items[index + 1] if index + 1 < len(items) else None
            if following is None or following["kind"] == "else":
                raise ParseError("IF%d has no statement to run after its condition." % item["id"])
        if item["kind"] == "block":
            check_items(item["inner"])


def parse_source(code):
    if not isinstance(code, str) or not code.strip():
        raise ParseError("Please type or paste some code first.")
    if len(code) > MAX_CODE_LENGTH:
        raise ParseError("The input is too long (limit: %d characters)." % MAX_CODE_LENGTH)

    clean_code, tokens = tokenize(code)
    if not tokens:
        raise ParseError("There is nothing to analyse (the input only contains comments).")

    counters = {"if": 0, "else": 0}
    items, _ = build_items(clean_code, tokens, 0, counters, 0)
    if counters["if"] == 0:
        raise ParseError("No 'if' statement found. Enter at least one if / if-else statement.")
    if counters["if"] > MAX_IFS:
        raise ParseError("Too many 'if' statements (limit: %d)." % MAX_IFS)

    check_items(items)
    return items, counters


def make_if_tree(if_item, then_tree, else_tree, else_item, cls):
    return {
        "t": "if",
        "id": if_item["id"],
        "cond": if_item["cond"],
        "then": then_tree,
        "else": else_tree,
        "else_id": else_item["id"] if else_item else None,
        "cls": cls,
    }


def else_rule(mode, kind):
    if mode == "ambiguous":
        return "S", "S", None
    if kind == "M":
        return "M", "M", "M"
    return "M", "U", "U"


def forest(items, mode):
    memo = {}

    def leaf_trees(item, cls):
        if item["kind"] == "other":
            return [{"t": "other", "text": item["text"], "cls": cls}]
        if item["kind"] == "block":
            return [{"t": "block", "stmts": body, "cls": cls} for body in forest(item["inner"], mode)]
        return []

    def trees(kind, i, j):
        key = (kind, i, j)
        if key not in memo:
            memo[key] = list(islice(derive(kind, i, j), TREE_LIMIT))
        return memo[key]

    def derive(kind, i, j):
        if i >= j:
            return

        if kind == "S" and mode == "unambiguous":
            yield from trees("M", i, j)
            yield from trees("U", i, j)
            return

        first = items[i]

        if j - i == 1:
            if kind != "U":
                yield from leaf_trees(first, "M" if mode == "unambiguous" else None)
            return

        if first["kind"] != "if":
            return

        if kind in ("S", "U"):
            for body in trees("S", i + 1, j):
                yield make_if_tree(first, body, None, None, "U" if kind == "U" else None)

        then_kind, else_kind, cls = else_rule(mode, kind)
        for k in range(i + 2, j - 1):
            if items[k]["kind"] != "else":
                continue
            for then_tree in trees(then_kind, i + 1, k):
                for else_tree in trees(else_kind, k + 1, j):
                    yield make_if_tree(first, then_tree, else_tree, items[k], cls)

    def statement_lists(i, j):
        key = ("list", i, j)
        if key not in memo:
            memo[key] = list(islice(derive_lists(i, j), TREE_LIMIT))
        return memo[key]

    def derive_lists(i, j):
        if i == j:
            yield []
            return
        for k in range(i + 1, j + 1):
            for first in trees("S", i, k):
                for rest in statement_lists(k, j):
                    yield [first] + rest

    return statement_lists(0, len(items))


def bindings(statements):
    result = {}

    def visit(node):
        if node["t"] == "if":
            if node["else_id"] is not None:
                result[node["else_id"]] = node["id"]
            visit(node["then"])
            if node["else"] is not None:
                visit(node["else"])
        elif node["t"] == "block":
            for statement in node["stmts"]:
                visit(statement)

    for statement in statements:
        visit(statement)
    return result


def collect_ifs(statements):
    found = []

    def visit(node, depth):
        if node["t"] == "if":
            found.append({"id": node["id"], "cond": node["cond"], "else_id": node["else_id"],
                          "cls": node["cls"], "depth": depth})
            visit(node["then"], depth + 1)
            if node["else"] is not None:
                visit(node["else"], depth + 1)
        elif node["t"] == "block":
            for statement in node["stmts"]:
                visit(statement, depth + 1)

    for statement in statements:
        visit(statement, 0)
    return sorted(found, key=lambda info: info["id"])


def collect_owners(parses):
    owners = {}
    for parse in parses:
        for else_id, if_id in bindings(parse).items():
            owners.setdefault(else_id, set()).add(if_id)
    return owners


def code_line(text, note=None, color=None):
    return {"text": text, "note": note, "color": color}


def pretty_lines(statements, depth=0):
    lines = []
    for statement in statements:
        lines += pretty_statement(statement, depth)
    return lines


def pretty_statement(node, depth):
    indent = "    " * depth

    if node["t"] == "other":
        return [code_line(indent + node["text"])]

    if node["t"] == "block":
        return ([code_line(indent + "{")]
                + pretty_lines(node["stmts"], depth + 1)
                + [code_line(indent + "}")])

    lines = [code_line(indent + "if (%s)" % node["cond"], "IF%d" % node["id"], node["id"])]
    lines += pretty_statement(node["then"], depth + 1)
    if node["else"] is not None:
        note = "else #%d → IF%d" % (node["else_id"], node["id"])
        lines.append(code_line(indent + "else", note, node["id"]))
        lines += pretty_statement(node["else"], depth + 1)
    return lines


def terminal_node(label, kind="term", sub=None, color=None):
    return {"label": label, "kind": kind, "sub": sub, "color": color, "children": []}


def inner_node(label, children, sub=None, kind=None):
    return {"label": label, "kind": kind or label, "sub": sub, "color": None, "children": children}


def if_condition_nodes(node):
    return [
        terminal_node("if", "if", "IF%d" % node["id"], node["id"]),
        terminal_node("E", "cond", node["cond"]),
        terminal_node("then"),
    ]


def else_node(node):
    sub = "else #%d → IF%d" % (node["else_id"], node["id"])
    return terminal_node("else", "else", sub, node["id"])


def block_node(node, render_statement):
    children = [render_statement(statement) for statement in node["stmts"]]
    return inner_node("{ block }", children, "statements inside { }", kind="block")


def render_original(node):
    if node["t"] == "other":
        return inner_node("S", [terminal_node("other", "other", node["text"])], "S → other")

    if node["t"] == "block":
        return inner_node("S", [block_node(node, render_original)], "S → other  (a { } block)")

    children = if_condition_nodes(node) + [render_original(node["then"])]
    production = "S → if E then S"
    if node["else"] is not None:
        children += [else_node(node), render_original(node["else"])]
        production = "S → if E then S else S"
    return inner_node("S", children, production)


def render_resolved(node, expected_kind):
    if expected_kind == "S":
        return inner_node("S", [render_resolved(node, node["cls"])], "S → " + node["cls"])

    if node["t"] == "other":
        return inner_node("M", [terminal_node("other", "other", node["text"])], "M → other")

    if node["t"] == "block":
        block = block_node(node, lambda statement: render_resolved(statement, "S"))
        return inner_node("M", [block], "M → other  (a { } block)")

    children = if_condition_nodes(node)
    if node["else"] is None:
        children.append(render_resolved(node["then"], "S"))
        production = "U → if E then S"
    elif node["cls"] == "M":
        children += [render_resolved(node["then"], "M"), else_node(node), render_resolved(node["else"], "M")]
        production = "M → if E then M else M"
    else:
        children += [render_resolved(node["then"], "M"), else_node(node), render_resolved(node["else"], "U")]
        production = "U → if E then M else U"
    return inner_node(node["cls"], children, production)


def render_program(statements, render_statement):
    if len(statements) == 1:
        return render_statement(statements[0])
    children = [render_statement(statement) for statement in statements]
    return inner_node("Program", children, "a list of statements", kind="prog")


def describe_count(count):
    return "%d or more" % TREE_LIMIT if count >= TREE_LIMIT else str(count)


def format_bindings(binding):
    return [{"else": else_id, "if": if_id} for else_id, if_id in sorted(binding.items())]


def summarize_bindings(binding):
    return "; ".join("else #%d belongs to IF%d" % (else_id, if_id)
                     for else_id, if_id in sorted(binding.items()))


def join_with_or(names):
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


def if_status(info):
    if info["else_id"] is None:
        return "unmatched – no else of its own"
    if info["cls"] == "U":
        return "unmatched – its else-branch ends in an unmatched if"
    return "matched – has its own else"


def build_verdict(is_ambiguous, else_count, tree_count):
    if is_ambiguous:
        return {
            "ambiguous": True,
            "title": "Dangling-else ambiguity detected",
            "message": "With the original grammar this code has %s different parse trees: the same "
                       "else can be attached to more than one if. The matched/unmatched grammar keeps "
                       "only one of them (the nearest if)." % tree_count,
        }
    if else_count == 0:
        message = ("There is no else clause, so no else can be attached in two ways. "
                   "Exactly one parse tree exists.")
    else:
        message = ("Every else has only one possible if to attach to, so the code has "
                   "exactly one parse tree.")
    return {"ambiguous": False, "title": "No ambiguity", "message": message}


def build_interpretations(parses, nearest):
    ordered = sorted(parses, key=lambda parse: 0 if bindings(parse) == nearest else 1)
    interpretations = []
    for number, parse in enumerate(ordered[:MAX_SHOWN], start=1):
        binding = bindings(parse)
        interpretations.append({
            "label": "Interpretation %d" % number,
            "is_nearest": binding == nearest,
            "bindings": format_bindings(binding),
            "summary": summarize_bindings(binding),
            "code": pretty_lines(parse),
            "tree": render_program(parse, render_original),
        })
    return interpretations


def build_if_table(resolved):
    table = []
    for info in collect_ifs(resolved):
        table.append({
            "id": info["id"],
            "cond": info["cond"],
            "depth": info["depth"],
            "class": info["cls"],
            "status": if_status(info),
            "else_id": info["else_id"],
        })
    return table


def explain_ambiguity(nearest, owners, conditions, tree_count):
    dangling = sorted(else_id for else_id, ifs in owners.items() if len(ifs) > 1)
    parts = []

    for else_id in dangling[:3]:
        candidates = join_with_or(["IF%d" % if_id for if_id in sorted(owners[else_id])])
        parts.append({
            "title": "Why else #%d is ambiguous" % else_id,
            "text": "else #%d could belong to %s. The original grammar allows every one of these, "
                    "so the same text has %s different parse trees. The nearest-unmatched-if rule "
                    "gives it to IF%d, the closest if above it that is still waiting for an else."
                    % (else_id, candidates, tree_count, nearest[else_id]),
        })

    parts.append({
        "title": "How the new grammar removes the ambiguity",
        "text": "In M → if E then M else M, the part between 'then' and 'else' must be a matched "
                "statement (M). An inner if without an else is unmatched (U), so it can never sit "
                "there. That blocks the else from 'jumping over' the inner if, so only the "
                "nearest-if meaning is left and the parse tree becomes unique.",
    })

    first_else = dangling[0]
    outer_if = sorted(owners[first_else])[0]
    inner_if = nearest[first_else]
    parts.append({
        "title": "Want the other meaning? Use braces",
        "text": "If you really want else #%d to belong to IF%d, close the inner if with braces: "
                "if (%s) { if (%s) ... } else ...  - braces end the inner statement, so no ambiguity remains."
                % (first_else, outer_if, conditions[outer_if], conditions[inner_if]),
    })
    return parts


def explain_no_ambiguity(nearest, else_count):
    if else_count == 0:
        text = ("There is no else clause, so there is nothing that could attach in two different "
                "ways. Every if is simply 'if E then S' (an unmatched statement U).")
    else:
        pairs = ", ".join("else #%d → IF%d" % (else_id, nearest[else_id]) for else_id in sorted(nearest))
        text = ("Every else has exactly one if it can attach to (%s). Either no unmatched if "
                "stands in between, or braces { } close the inner if. With only one possible "
                "parse tree, the original grammar and the matched/unmatched grammar agree." % pairs)
    return [{"title": "Why there is no ambiguity here", "text": text}]


def build_explanation(is_ambiguous, nearest, owners, conditions, else_count, tree_count):
    parts = [{
        "title": "The nearest-unmatched-if rule",
        "text": "An else clause is associated with the nearest preceding unmatched if statement. "
                "'Unmatched' means the if has not received an else yet. Real compilers (C, Java ...) "
                "use exactly this rule.",
    }]

    if is_ambiguous:
        parts += explain_ambiguity(nearest, owners, conditions, tree_count)
    else:
        parts += explain_no_ambiguity(nearest, else_count)

    parts.append({
        "title": "Matched vs unmatched",
        "text": "M (matched) = every if has its own else. U (unmatched) = some if is still waiting for "
                "an else. An else may only close an unmatched if, and the nearest one wins.",
    })
    return parts


def analyze(code):
    items, counters = parse_source(code)

    all_parses = forest(items, "ambiguous")
    if not all_parses:
        raise ParseError(
            "The if/else structure is not valid: some 'else' has no unmatched 'if' before it. "
            "A common cause is a ';' or statement placed between an if-body and its else.")

    resolved_parses = forest(items, "unambiguous")
    if len(resolved_parses) != 1:
        raise ParseError("Internal check failed: the transformed grammar did not give exactly one tree.")

    resolved = resolved_parses[0]
    nearest = bindings(resolved)
    owners = collect_owners(all_parses)
    is_ambiguous = len(all_parses) > 1
    tree_count = describe_count(len(all_parses))
    interpretations = build_interpretations(all_parses, nearest)
    if_table = build_if_table(resolved)
    conditions = {row["id"]: row["cond"] for row in if_table}

    dangling = [{"else": else_id, "candidates": sorted(if_ids), "chosen": nearest[else_id]}
                for else_id, if_ids in sorted(owners.items()) if len(if_ids) > 1]

    return {
        "ok": True,
        "verdict": build_verdict(is_ambiguous, counters["else"], tree_count),
        "counts": {
            "ifs": counters["if"],
            "elses": counters["else"],
            "original_trees": tree_count,
            "resolved_trees": "1",
        },
        "dangling": dangling,
        "ifs": if_table,
        "interpretations": interpretations,
        "hidden_interpretations": max(0, len(all_parses) - len(interpretations)),
        "resolved": {
            "bindings": format_bindings(nearest),
            "summary": summarize_bindings(nearest) or "There is no else clause.",
            "code": pretty_lines(resolved),
            "tree": render_program(resolved, lambda statement: render_resolved(statement, "S")),
        },
        "explanation": build_explanation(
            is_ambiguous, nearest, owners, conditions, counters["else"], tree_count),
    }


TEST_CASES = [
    {"name": "Classic dangling else (C style)",
     "code": "if (a) if (b) x = 1; else y = 2;",
     "expected": "ambiguous"},
    {"name": "Pseudo-code with 'then'",
     "code": "if E1 then if E2 then S1 else S2",
     "expected": "ambiguous"},
    {"name": "Three nested ifs, one else",
     "code": "if (a)\n  if (b)\n    if (c) x = 1;\n    else y = 2;",
     "expected": "ambiguous"},
    {"name": "Braces remove the ambiguity",
     "code": "if (a) {\n  if (b) x = 1;\n} else y = 2;",
     "expected": "unambiguous"},
    {"name": "Fully matched (every if has an else)",
     "code": "if (a) if (b) x = 1; else y = 2; else z = 3;",
     "expected": "unambiguous"},
    {"name": "No else at all",
     "code": "if (a) if (b) x = 1;",
     "expected": "unambiguous"},
    {"name": "else-if chain",
     "code": "if (a) x = 1;\nelse if (b) y = 2;\nelse z = 3;",
     "expected": "unambiguous"},
    {"name": "Dangling else hidden in an else-branch",
     "code": "if (a) x = 1;\nelse if (b) if (c) y = 2; else z = 3;",
     "expected": "ambiguous"},
    {"name": "Two statements, first one dangling",
     "code": "if (a) if (b) x = 1; else y = 2;\nif (c) z = 3;",
     "expected": "ambiguous"},
]


def run_test_case(number, case):
    entry = {"id": number, "name": case["name"], "code": case["code"], "expected": case["expected"]}
    try:
        info = analyze(case["code"])
        entry["result"] = "ambiguous" if info["verdict"]["ambiguous"] else "unambiguous"
        entry["trees"] = info["counts"]["original_trees"]
    except ParseError as error:
        entry["result"] = "error"
        entry["trees"] = "-"
        entry["error"] = str(error)
    entry["passed"] = entry["result"] == entry["expected"]
    return entry


def run_test_cases():
    return [run_test_case(number, case) for number, case in enumerate(TEST_CASES, start=1)]


if __name__ == "__main__":
    for result in run_test_cases():
        status = "PASS" if result["passed"] else "FAIL"
        print("%s  %-45s expected=%-11s got=%-11s trees=%s" % (
            status, result["name"], result["expected"], result["result"], result["trees"]))