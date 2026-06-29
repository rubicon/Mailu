"""Regression test for #2715:

`flask mailu config-import` (full replace, clear=True) issues bulk
``DELETE FROM`` statements via ``MailuConfig.clear()``. Bulk deletes neither
respect FK ordering nor trigger ORM cascades / m2m secondary cleanup, so under a
FK-enforcing backend (PostgreSQL; SQLite with ``PRAGMA foreign_keys=ON``) the
delete violates ``user_domain_name_fkey`` and friends.

We enable SQLite FK enforcement to mimic PostgreSQL and assert that clearing the
config does not raise an IntegrityError.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mailu import models


def _set_sqlite_fk(on):
    """Toggle FK enforcement on the current (in-memory, single) connection so
    SQLite behaves like PostgreSQL. Turned off again before teardown's
    drop_all() so dropping the tables is not blocked by FKs."""
    models.db.session.execute(text(f"PRAGMA foreign_keys={'ON' if on else 'OFF'}"))


def _seed(app):
    """Create a domain referenced by a user, a manager (m2m) row, an alias,
    an alternative, a token and a domain-access row -- i.e. every relationship
    that points at domain/user."""
    domain = models.Domain(name='example.com')
    models.db.session.add(domain)
    models.db.session.commit()

    user = models.User(localpart='alice', domain_name='example.com')
    user.set_password('password')
    models.db.session.add(user)
    models.db.session.commit()

    # m2m manager association row (the 'manager' table, no ON DELETE)
    domain.managers.append(user)

    token = models.Token(user_email=user.email)
    token.set_password('b' * 32)
    models.db.session.add(token)

    alias = models.Alias(
        localpart='info',
        domain_name='example.com',
        destination=['alice@example.com'],
    )
    models.db.session.add(alias)

    alt = models.Alternative(name='alt.example.com', domain_name='example.com')
    models.db.session.add(alt)

    da = models.DomainAccess(domain_name='example.com', user_email=user.email)
    models.db.session.add(da)

    models.db.session.commit()


def test_config_clear_does_not_violate_fk(app):
    with app.app_context():
        _seed(app)
        _set_sqlite_fk(True)
        try:
            config = models.MailuConfig()
            # same model-set the import schema passes (config-import full replace)
            model_set = {models.Domain, models.User, models.Alias, models.Relay}

            try:
                config.clear(models=model_set)
                models.db.session.flush()
            except IntegrityError as exc:
                models.db.session.rollback()
                pytest.fail(f'config clear raised FK violation (#2715): {exc.orig}')

            # everything that was cleared (and its dependents) must be gone
            assert models.Domain.query.count() == 0
            assert models.User.query.count() == 0
            assert models.Alias.query.count() == 0
            assert models.Alternative.query.count() == 0
            assert models.DomainAccess.query.count() == 0
            assert models.Token.query.count() == 0
            assert models.db.session.execute(
                text('SELECT COUNT(*) FROM manager')
            ).scalar() == 0
        finally:
            # let teardown's drop_all() run without FK enforcement
            models.db.session.rollback()
            _set_sqlite_fk(False)
