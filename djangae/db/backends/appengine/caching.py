import logging
import threading
import itertools

from google.appengine.api import datastore
from google.appengine.api import namespace_manager

from django.conf import settings
from django.core.cache import cache
from djangae.db import utils
from djangae.db.unique_utils import unique_identifiers_from_entity, _format_value_for_identifier
from djangae.db.backends.appengine.context import ContextStack

logger = logging.getLogger("djangae")

_context = None

def get_context():
    global _context

    if not _context:
        _context = threading.local()

    return _context


CACHE_TIMEOUT_SECONDS = getattr(settings, "DJANGAE_CACHE_TIMEOUT_SECONDS", 60 * 60)
CACHE_ENABLED = getattr(settings, "DJANGAE_CACHE_ENABLED", True)


class CachingSituation:
    DATASTORE_GET = 0
    DATASTORE_PUT = 1
    DATASTORE_GET_PUT = 2 # When we are doing an update


def ensure_context():
    context = get_context()

    context.memcache_enabled = getattr(context, "memcache_enabled", True)
    context.context_enabled = getattr(context, "context_enabled", True)
    context.stack = context.stack if hasattr(context, "stack") else ContextStack()


def _apply_namespace(value_or_map):
    namespace = namespace_manager.get_namespace()

    if hasattr(value_or_map, "keys"):
        return { "{}:{}".format(namespace, k):v for k,v in value_or_map.iteritems() }
    elif hasattr(value_or_map, "__iter__"):
        return [ "{}:{}".format(namespace, x) for x in value_or_map ]
    else:
        return "{}:{}".format(namespace, value_or_map)

def _strip_namespace(value_or_map):
    def _strip(value):
        return value.split(":",1)[-1]

    if hasattr(value_or_map, "keys"):
        return { _strip(k):v for k,v in value_or_map.iteritems() }
    elif hasattr(value_or_map, "__iter__"):
        return [ _strip(x) for x in value_or_map ]
    else:
        return _strip(value_or_map)


def _add_entity_to_memcache(model, mc_key_entity_map):
    cache.set_many(_apply_namespace(mc_key_entity_map), timeout=CACHE_TIMEOUT_SECONDS)


def _get_cache_key_and_model_from_datastore_key(key):
    model = utils.get_model_from_db_table(key.kind())

    if not model:
        # This should never happen.. if it does then we can edit get_model_from_db_table to pass
        # include_deferred=True/included_swapped=True to get_models, whichever makes it better
        raise AssertionError("Unable to locate model for db_table '{}' - item won't be evicted from the cache".format(key.kind()))

    # We build the cache key for the ID of the instance
    cache_key =  "|".join([key.kind(), "{}:{}".format(model._meta.pk.column,  _format_value_for_identifier(key.id_or_name()))])

    return (cache_key, model)


def _remove_entities_from_memcache_by_key(keys):
    """
        Note, if the key of the entity got evicted from the cache, it's possible that stale cache
        entries would be left behind. Remember if you need pure atomicity then use disable_cache() or a
        transaction.
    """

    # Key -> model
    cache_keys = dict(
        _get_cache_key_and_model_from_datastore_key(key) for key in keys
    )
    entities = _strip_namespace(cache.get_many(_apply_namespace(cache_keys.keys())))

    if entities:
        identifiers = [
            unique_identifiers_from_entity(cache_keys[key], entity)
            for key, entity in entities.items()
        ]
        cache.delete_many(_apply_namespace(itertools.chain(*identifiers)))


def _get_entity_from_memcache(identifier):
    return cache.get(_apply_namespace(identifier))


def _get_entity_from_memcache_by_key(key):
    # We build the cache key for the ID of the instance
    cache_key, _ = _get_cache_key_and_model_from_datastore_key(key)
    return cache.get(_apply_namespace(cache_key))


def add_entities_to_cache(model, entities, situation, skip_memcache=False):
    ensure_context()

    # Don't cache on Get if we are inside a transaction, even in the context
    # This is because transactions don't see the current state of the datastore
    # We can still cache in the context on Put() but not in memcache
    if situation == CachingSituation.DATASTORE_GET and datastore.IsInTransaction():
        return

    if situation in (CachingSituation.DATASTORE_PUT, CachingSituation.DATASTORE_GET_PUT) and datastore.IsInTransaction():
        # We have to wipe the entity from memcache
        _remove_entities_from_memcache_by_key([entity.key() for entity in entities if entity.key()])

    identifiers = [
        unique_identifiers_from_entity(model, entity) for entity in entities
    ]

    for ent_identifiers, entity in zip(identifiers, entities):
        get_context().stack.top.cache_entity(_apply_namespace(ent_identifiers), entity, situation)

    # Only cache in memcache of we are doing a GET (outside a transaction) or PUT (outside a transaction)
    # the exception is GET_PUT - which we do in our own transaction so we have to ignore that!
    if (not datastore.IsInTransaction() and situation in (CachingSituation.DATASTORE_GET, CachingSituation.DATASTORE_PUT)) or \
            situation == CachingSituation.DATASTORE_GET_PUT:

        if not skip_memcache:

            mc_key_entity_map = {}
            for ent_identifiers, entity in zip(identifiers, entities):
                mc_key_entity_map.update({
                    identifier: entity for identifier in ent_identifiers
                })
            _add_entity_to_memcache(model, mc_key_entity_map)


def remove_entities_from_cache(entities):
    keys = [entity.key() for entity in entities if entity.key()]
    remove_entities_from_cache_by_key(keys)


def remove_entities_from_cache_by_key(keys, memcache_only=False):
    """
        Removes an entity from all caches (both context and memcache)
        or just memcache if specified
    """
    ensure_context()

    if not memcache_only:
        for key in keys:
            for identifier in _context.stack.top.reverse_cache.get(_apply_namespace(key), []):
                if identifier in _context.stack.top.cache:
                    del _context.stack.top.cache[identifier]

    _remove_entities_from_memcache_by_key(keys)


def get_from_cache_by_key(key):
    """
        Return an entity from the context cache, falling back to memcache when possible
    """

    ensure_context()

    if not CACHE_ENABLED:
        return None

    ret = None
    if _context.context_enabled:
        # It's safe to hit the context cache, because a new one was pushed on the stack at the start of the transaction
        ret = _context.stack.top.get_entity_by_key(_apply_namespace(key))
        if ret is None and not datastore.IsInTransaction():
            if _context.memcache_enabled:
                ret = _get_entity_from_memcache_by_key(key)
                if ret:
                    # Add back into the context cache
                    add_entities_to_cache(
                        utils.get_model_from_db_table(ret.key().kind()),
                        [ret],
                        CachingSituation.DATASTORE_GET,
                        skip_memcache=True # Don't put in memcache, we just got it from there!
                    )
    elif _context.memcache_enabled and not datastore.IsInTransaction():
        ret = _get_entity_from_memcache_by_key(key)

    return ret


def get_from_cache(unique_identifier):
    """
        Return an entity from the context cache, falling back to memcache when possible
    """

    ensure_context()
    context = get_context()

    if not CACHE_ENABLED:
        return None

    ret = None
    if context.context_enabled:
        # It's safe to hit the context cache, because a new one was pushed on the stack at the start of the transaction
        ret = context.stack.top.get_entity(_apply_namespace(unique_identifier))
        if ret is None and not datastore.IsInTransaction():
            if context.memcache_enabled:
                ret = _get_entity_from_memcache(unique_identifier)
                if ret:
                    # Add back into the context cache
                    add_entities_to_cache(
                        utils.get_model_from_db_table(ret.key().kind()),
                        [ret],
                        CachingSituation.DATASTORE_GET,
                        skip_memcache=True # Don't put in memcache, we just got it from there!
                    )

    elif context.memcache_enabled and not datastore.IsInTransaction():
        ret = _get_entity_from_memcache(unique_identifier)

    return ret


def reset_context(keep_disabled_flags=False, *args, **kwargs):
    """
        Called at the beginning and end of each request, resets the thread local
        context. If you pass keep_disabled_flags=True the memcache_enabled and context_enabled
        flags will be preserved, this is really only useful for testing.
    """

    context = get_context()

    memcache_enabled = getattr(context, "memcache_enabled", True)
    context_enabled = getattr(context, "context_enabled", True)

    context.memcache_enabled = True
    context.context_enabled = True
    context.stack = ContextStack()

    if keep_disabled_flags:
        context.memcache_enabled = memcache_enabled
        context.context_enabled = context_enabled
