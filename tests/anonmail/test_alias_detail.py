"""Regression tests for #2988: recipient-delimiter detail must be preserved
when an address resolves through an explicit (non-wildcard) alias."""
import os

from mailu import models


def _base(app):
    os.environ['RECIPIENT_DELIMITER'] = '+'
    models.db.session.add(models.Domain(name='example.com'))
    user = models.User(localpart='joe', domain_name='example.com')
    user.set_password('password')
    models.db.session.add(user)
    models.db.session.add(models.Alias(
        localpart='team', domain_name='example.com',
        destination=['joe@example.com'], wildcard=False))
    models.db.session.commit()


class TestAliasRecipientDelimiter:

    def test_explicit_alias_preserves_detail(self, app):
        """alias+detail must keep the +detail on the destination (the #2988 bug)."""
        with app.app_context():
            _base(app)
            # sanity: plain alias and plain user unchanged
            assert models.Email.resolve_destination('team', 'example.com') == ['joe@example.com']
            assert models.Email.resolve_destination('joe', 'example.com') == ['joe@example.com']
            # the fix: +detail is re-attached to the alias destination
            assert models.Email.resolve_destination('team+test', 'example.com') == ['joe+test@example.com']

    def test_user_detail_unchanged(self, app):
        """user+detail already worked and must stay unchanged."""
        with app.app_context():
            _base(app)
            assert models.Email.resolve_destination('joe+test', 'example.com') == ['joe+test@example.com']

    def test_catchall_does_not_swallow_explicit_alias_detail(self, app):
        """With a catch-all present, alias+detail must still reach the explicit
        alias (not the catch-all), and the catch-all itself stays unchanged."""
        with app.app_context():
            _base(app)
            models.db.session.add(models.Alias(
                localpart='%', domain_name='example.com',
                destination=['catchall@example.com'], wildcard=True))
            models.db.session.commit()
            # explicit alias wins over catch-all, detail preserved
            assert models.Email.resolve_destination('team+test', 'example.com') == ['joe+test@example.com']
            # catch-all behaviour is untouched
            assert models.Email.resolve_destination('random', 'example.com') == ['catchall@example.com']
            assert models.Email.resolve_destination('random+x', 'example.com') == ['catchall@example.com']

    def test_multiple_destinations_each_get_detail(self, app):
        with app.app_context():
            os.environ['RECIPIENT_DELIMITER'] = '+'
            models.db.session.add(models.Domain(name='example.com'))
            models.db.session.add(models.Alias(
                localpart='all', domain_name='example.com',
                destination=['a@example.com', 'b@other.org'], wildcard=False))
            models.db.session.commit()
            assert models.Email.resolve_destination('all+sales', 'example.com') == \
                ['a+sales@example.com', 'b+sales@other.org']

    def test_postfix_endpoint_returns_detail(self, app, client):
        with app.app_context():
            _base(app)
            rv = client.get('/internal/postfix/alias/team+test@example.com')
            assert rv.status_code == 200
            assert 'joe+test@example.com' in rv.get_json()
