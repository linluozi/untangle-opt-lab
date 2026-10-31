#!/usr/bin/env python3
"""
Differential test: baseline untangle vs indexed untangle, byte-for-byte.

Every case parses the same input with both implementations and compares a
canonical JSON serialization of the whole tree (name, attributes, cdata,
children order) plus every tag query. No tolerances are used.

Run:
    python -m pytest tests/test_diff.py -q
"""

import importlib.util
import json
import random
from pathlib import Path

import pytest
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent.parent
SEED = 20261031
RANDOM_CASES = 1200


def load(name):
    path = ROOT / "src" / f"untangle_{name}.py"
    spec = importlib.util.spec_from_file_location(f"untangle_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = load("baseline")
optimized = load("optimized")


def snapshot(element):
    return {
        "name": element._name,
        "attributes": element._attributes,
        "cdata": element.cdata,
        "children": [snapshot(child) for child in element.children],
    }


def canonical(element):
    return json.dumps(snapshot(element), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


TAGS = ["alpha", "beta", "gamma", "delta", "item", "node", "类", "ü", "tag-with-dash", "tag.dot", "class"]
ATTRS = ["id", "name", "data-x", "ü"]
VALUES = ["", "plain", "<&>\"'", "héllo 世界", "line\nbreak", "  spaced  ", "a" * 200, "0"]
TEXTS = ["", "text", "héllo 世界", "<&>\"'", "  padded  ", "line\nbreak", "x" * 300]


def gen_element(rng, depth):
    tag = rng.choice(TAGS)
    attrs = {}
    for _ in range(rng.randint(0, 2)):
        attrs[rng.choice(ATTRS)] = rng.choice(VALUES)
    children = []
    if depth > 0:
        for _ in range(rng.randint(0, 4)):
            children.append(gen_element(rng, depth - 1))
    text = rng.choice(TEXTS) if not children else rng.choice(["", "\n  "])
    attr_text = "".join(f" {k}={quoteattr(v)}" for k, v in attrs.items())
    if rng.random() < 0.15:
        # CDATA payload (never contains the terminator)
        body = "<![CDATA[" + text.replace("]]>", "]]&gt;") + "]]>"
    else:
        body = escape(text)
    body += "".join(children)
    return f"<{tag}{attr_text}>{body}</{tag}>"


def gen_document(rng):
    children = [gen_element(rng, 3) for _ in range(rng.randint(0, 4))]
    return "<root>" + "".join(children) + "</root>"


EDGE_XML = [
    "<root/>",
    "<root></root>",
    "<root><a/></root>",
    "<root><a>1</a></root>",
    "<root><a>1</a><a>2</a><a>3</a></root>",
    "<root><类>世界</类></root>",
    "<root><a b='1' c=\"2\">x</a></root>",
    "<root><a><![CDATA[<&>]]></a></root>",
    "<root><!-- comment --><a>1</a><?pi go?></root>",
    "<root><class>kw</class><tag-with-dash>d</tag-with-dash><tag.dot>p</tag.dot></root>",
    "<root>" + "".join(f"<s{i}>v{i}</s{i}>" for i in range(500)) + "</root>",
    "<root>" + "<d>" * 100 + "deep" + "</d>" * 100 + "</root>",
    "<root><a>" + "z" * 10000 + "</a></root>",
    "<root><a x='&lt;&amp;&gt;'>t</a></root>",
    "<?xml version='1.0' encoding='UTF-8'?><root><a>é</a></root>",
]

INVALID_XML = [
    None,
    "",
    "   ",
    "<root>",
    "<a></b>",
    "not xml",
    "<root><a></root>",
    "<!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><foo>&xxe;</foo>",
]


def assert_same_tree(xml, label):
    a = baseline.parse(xml)
    b = optimized.parse(xml)
    assert canonical(a) == canonical(b), f"tree mismatch: {label}"
    assert str(a) == str(b), f"str mismatch: {label}"
    assert repr(a) == repr(b), f"repr mismatch: {label}"
    assert dir(a) == dir(b), f"dir mismatch: {label}"
    for tag in TAGS:
        left = [canonical(x) for x in a.get_elements(tag)]
        right = [canonical(x) for x in b.get_elements(tag)]
        assert left == right, f"get_elements({tag!r}) mismatch: {label}"
        assert hasattr(a, tag) == hasattr(b, tag), f"hasattr({tag!r}) mismatch: {label}"
        assert (tag in a) == (tag in b), f"contains({tag!r}) mismatch: {label}"
    assert a.get_elements(None) is a.children
    assert b.get_elements(None) is b.children


def test_random_documents_are_byte_identical():
    rng = random.Random(SEED)
    for i in range(RANDOM_CASES):
        xml = gen_document(rng)
        assert_same_tree(xml, f"random[{i}] seed={SEED}")


def test_edge_documents_are_byte_identical():
    for i, xml in enumerate(EDGE_XML):
        assert_same_tree(xml, f"edge[{i}]")


def test_invalid_inputs_raise_identically():
    for i, xml in enumerate(INVALID_XML):
        errors = []
        for module in (baseline, optimized):
            with pytest.raises(Exception) as excinfo:
                module.parse(xml)
            errors.append((type(excinfo.value).__name__, str(excinfo.value)))
        assert errors[0] == errors[1], f"exception mismatch: invalid[{i}]"


def test_add_child_and_direct_list_mutation():
    for module in (baseline, optimized):
        root = module.Element("root", {})
        first = module.Element("x", {})
        second = module.Element("x", {})
        root.add_child(first)
        assert root.get_elements("x") == [first]
        assert root.x is first
        root.children.append(second)
        assert root.get_elements("x") == [first, second]
        del root.children[0]
        assert root.get_elements("x") == [second]
        assert root.get_elements("missing") == []


def test_case_count_gate():
    assert RANDOM_CASES + len(EDGE_XML) >= 1000
