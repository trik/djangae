from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _

class DjangaeConfig(AppConfig):
    name = 'djangae'
    verbose_name = _("Djangae")

    def ready(self):
        from .patches.contenttypes import patch
        patch(sender=self)

        from .patches import models
        models.patch()

        from djangae.db.backends.appengine.caching import reset_context
        from django.core.signals import request_finished, request_started

        request_finished.connect(reset_context, dispatch_uid="request_finished_context_reset")
        request_started.connect(reset_context, dispatch_uid="request_started_context_reset")
