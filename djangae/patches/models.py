def patch():
    """
    Disable creation of foreign key constraints, unsupported from Google Cloud SQL
    """
    from django.db.models import get_apps, get_models
    from django.db.models.fields.related import RelatedField

    for app in get_apps():
        for model in get_models(app):
            for field in model._meta.get_fields(include_parents=False):
                if isinstance(field, RelatedField):
                    field.db_constraint = False
