import pytest
from article_agent.evaluation.comparators import compare_values
from article_agent.evaluation.registry import load_registry


def spec(kind, **config):
    return load_registry().fields[0].model_copy(update={"comparator":{"type":kind,**config}})


@pytest.mark.parametrize("kind,a,b,expected",[
    ("EXACT_VALUE",2,2,True),("EXACT_VALUE",2,"2",False),
    ("EXACT_VALUE","A","a",False),("SEMANTIC_CODE",2,2,True),
    ("SEMANTIC_CODE",1,"yes",False),
    ("NORMALIZED_STRING","  Acupunct   Med ","acupunct med",True),
    ("NORMALIZED_STRING","Ａ","a",True),("NORMALIZED_STRING","pain-score","pain score",False),
    ("NORMALIZED_NUMERIC",1.0,1.0000001,True),("NORMALIZED_NUMERIC",1.0,1.1,False),
    ("ORDERED_LIST",["A","B"],["b","a"],False),
    ("UNORDERED_LIST",["A","B"],["b","a"],True),
    ("UNORDERED_LIST",["A","A"],["a"],False),
    ("SET_EQUALITY",["A","A"],["a"],True),
    ("STATUS_ONLY","PRESENT","PRESENT",True),
    ("STATUS_ONLY","PRESENT","NOT_REPORTED",False),
    ("EVIDENCE_GROUNDED",True,True,True),("EVIDENCE_GROUNDED",True,False,False),
])
def test_comparators(kind,a,b,expected):
    assert compare_values(a,b,spec(kind)).matched is expected


def test_numeric_relative_tolerance():
    assert compare_values(100,101,spec("NORMALIZED_NUMERIC",relative_tolerance=.02)).matched


@pytest.mark.parametrize("a,b",[("1",1),(float("inf"),1),(True,1)])
def test_no_numeric_coercion(a,b):
    with pytest.raises(ValueError): compare_values(a,b,spec("NORMALIZED_NUMERIC"))


def test_explicit_normalization_and_unknown_ops():
    f=spec("EXACT_VALUE").model_copy(update={"normalization":["casefold"]})
    assert compare_values("A","a",f).matched
    with pytest.raises(ValueError):
        compare_values("a","a",f.model_copy(update={"normalization":["guess"]}))
    with pytest.raises(ValueError): compare_values(1,1,spec("unknown"))
