import pytest

from toad_server.memory_policy import allows_save


@pytest.mark.parametrize(
    "words",
    [
        "Remember that I prefer tea.",
        "Hey Toad, note my desk number.",
        "Could you please remember my name?",
        "Make a note of this.",
        "Today was busy. Remember that I work mornings.",
        "I’d like you to save my preference.",
    ],
)
def test_explicit_memory_requests(words: str) -> None:
    assert allows_save(words, None)


@pytest.mark.parametrize(
    "words",
    [
        "Do you remember my name?",
        "I don't remember my password.",
        "Remember when we met?",
        "What did I ask you to remember?",
        "I like tea.",
        "",
        "yes",
    ],
)
def test_questions_and_ambient_chat_do_not_authorize_save(words: str) -> None:
    assert not allows_save(words, None)


def test_yes_only_after_memory_offer() -> None:
    assert allows_save("yes please", "Shall I remember that?")
    assert not allows_save("yes please", "Would you like a break?")
    assert not allows_save("no thanks", "Shall I remember that?")
