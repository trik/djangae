#LIBRARIES
import django
import contextlib

from django.db.models.sql import compiler

#DJANGAE
from .commands import (
    SelectCommand,
    InsertCommand,
    UpdateCommand,
    DeleteCommand
)

@contextlib.contextmanager
def active_namespace(namespace):
    from google.appengine.api import namespace_manager

    try:
        original_namespace = namespace_manager.get_namespace()
        namespace_manager.set_namespace(namespace)
        yield
    finally:
        namespace_manager.set_namespace(original_namespace)


class SQLCompiler(compiler.SQLCompiler):
    def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
        self.pre_sql_setup()
        self.refcounts_before = self.query.alias_refcount.copy()

        select = SelectCommand(
            self.connection,
            self.query
        )
        return (select, tuple())

    def get_select(self):
        self.query.select_related = False # Make sure select_related is disabled for all queries
        return super(SQLCompiler, self).get_select()


class SQLInsertCompiler(SQLCompiler, compiler.SQLInsertCompiler):
    def __init__(self, *args, **kwargs):
        self.return_id = None
        super(SQLInsertCompiler, self).__init__(*args, **kwargs)

    def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
        self.pre_sql_setup()

        from djangae.db.utils import get_concrete_fields

        # Always pass down all the fields on an insert
        return [ (InsertCommand(
            self.connection, self.query.model, self.query.objs,
            list(self.query.fields) + list(get_concrete_fields(self.query.model, ignore_leaf=True)),
            self.query.raw), tuple())
        ]


class SQLDeleteCompiler(SQLCompiler, compiler.SQLDeleteCompiler):
    def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
        return (DeleteCommand(self.connection, self.query), tuple())


class SQLUpdateCompiler(SQLCompiler, compiler.SQLUpdateCompiler):
    def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
        self.pre_sql_setup()
        return (UpdateCommand(self.connection, self.query), tuple())


class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
        if self.query.subquery:
            self.query.high_mark = self.query.subquery.query.high_mark
            self.query.low_mark = self.query.subquery.query.low_mark
        return SQLCompiler.as_sql(self, with_limits, with_col_aliases, subquery)


if django.VERSION < (1, 8):
    from django.db.models.sql.compiler import (
        SQLDateCompiler as DateCompiler,
        SQLDateTimeCompiler as DateTimeCompiler
    )

    class SQLDateCompiler(DateCompiler, SQLCompiler):
        def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
            return SQLCompiler.as_sql(self, with_limits, with_col_aliases, subquery)


    class SQLDateTimeCompiler(DateTimeCompiler, SQLCompiler):
        def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
            return SQLCompiler.as_sql(self, with_limits, with_col_aliases, subquery)
