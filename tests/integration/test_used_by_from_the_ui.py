"""The "used by" report over HTTP (the ontology's shape, 27 October).

It is read-only and runs against the fixture configuration. The rules
under test: only a manager of the deployment may ask; a type, a field and
a link each answer with what names them; an unknown name is "Not found"
and says nothing else; an ambiguous question is refused; and the answer
always says what it does not look at.
"""

import pytest

from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _login

config_dir = editing.config_dir
deployer = editing.deployer
PATH = "/api/admin/ontology/used-by"


def _rows(response):
    assert response.status_code == 200, response.text
    return {(row["kind"], row["place"]) for row in response.json()["referrers"]}


class TestTheReport:
    def test_a_type_lists_its_links_roles_and_actions(self, deployer):
        rows = _rows(deployer.get(PATH, params={"object_type": "Customer"}))

        assert ("link", "link CustomerAccounts") in rows
        assert ("grant", "role customer_service") in rows
        assert ("action", "action CreateCustomer") in rows
        assert ("security", "Account row rule") in rows

    def test_a_field_lists_what_reads_it(self, deployer):
        rows = _rows(deployer.get(PATH, params={"object_type": "Customer", "field": "name"}))

        assert ("title", "type Customer") in rows
        assert ("action", "action UpdateCustomerName") in rows
        assert ("grant", "role editor") in rows

    def test_a_link_lists_what_names_either_end(self, deployer):
        rows = _rows(deployer.get(PATH, params={"link": "CustomerAccounts"}))

        assert ("grant", "role debug") in rows
        assert ("security", "type Account, row rule") in rows

    def test_a_field_nothing_names_has_no_rows(self, deployer):
        response = deployer.get(PATH, params={"object_type": "Account", "field": "currency"})

        assert response.status_code == 200 and response.json()["referrers"] == []

    def test_every_answer_says_what_it_does_not_look_at(self, deployer):
        answer = deployer.get(PATH, params={"object_type": "Account", "field": "currency"}).json()

        assert "Saved views" in answer["not_listed"]


class TestWhoMayAskAndWhatIsRefused:
    @pytest.mark.parametrize("params", [{"object_type": "Nobody"}, {"object_type": "Customer", "field": "nope"},
                                        {"link": "NoSuchLink"}])
    def test_an_unknown_name_is_not_found(self, deployer, params):
        assert deployer.get(PATH, params=params).status_code == 404

    @pytest.mark.parametrize("params", [{}, {"field": "name"}, {"link": "CustomerAccounts", "object_type": "Customer"}])
    def test_an_unclear_question_is_refused(self, deployer, params):
        assert deployer.get(PATH, params=params).status_code == 400

    def test_only_a_manager_of_the_deployment_may_ask(self, deployer):
        deployer.cookies.clear()
        deployer.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(deployer, "pat", "correct-pw")

        assert deployer.get(PATH, params={"object_type": "Customer"}).status_code == 403
