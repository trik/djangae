# Installation

**If you just want to get started on a fresh Django project, take a look at [djangae-scaffold](https://github.com/potatolondon/djangae-scaffold)**

Alternatively, you can also follow this guide:

1. Create a Django project, add app.yaml to the root. Make sure Django 1.7+ is in your project and importable
 

2. Install Djangae into your project, make sure it's importable (you'll likely need to manipulate the path in manage.py and wsgi.py)
 

3. Add djangae to `INSTALLED_APPS`.
 
 
4. At the top of your `settings.py`, insert the following line to setup some default settings: 

```python
from djangae.settings_base import *`
```

In `app.yaml` add the following handlers:

```yml
* url: /_ah/(mapreduce|queue|warmup).*
  script: YOUR_DJANGO_APP.wsgi.application
  login: admin

* url: /.*
  script: YOUR_DJANGO_APP.wsgi.application
```

If you are planning to use remote management commands, in `app.yaml` add the following handler:

```yml
* url: /_ah/remote_api(/.*)?
  script: google.appengine.ext.remote_api.handler.application
```

Make your `manage.py` look something like this:

```python
if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myapp.settings")

    from djangae.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
```

Use the Djangae WSGI handler in your wsgi.py, something like

```python
from django.core.wsgi import get_wsgi_application

from djangae.wsgi import DjangaeApplication

application = DjangaeApplication(get_wsgi_application())
```

Add the following to your URL handler: 

```python
url(r'^_ah/', include('djangae.urls'))
```

It is recommended that for improved security you add `djangae.contrib.security.middleware.AppEngineSecurityMiddleware` as the first of your middleware classes. This middleware patches a number of insecure parts of the Python and App Engine libraries and warns if your Django settings aren't as secure as they could be.

> If you wish to use the App Engine's Google Accounts-based authentication to authenticate your users, and/or you wish to use Django's permissions system with the Datastore as you DB, then see the section on **Authentication**.

> **It is highly recommended that you read the section on [Unique Constraints](db_backend/#unique-constraint-checking)**

## Deployment

Create a Google App Engine project. 

Edit `app.yaml` and change 

```yml
application: [...]
```
to

```yml
application: your-app-id
```

Then run:

    $ appcfg.py update ./

If you have two-factor authentication enabled in your Google account, run:

    $ appcfg.py --oauth2 update ./

## Modules

If you are using multiple modules in your app. Just set the following setting in your Django settings:

DJANGAE_ADDITIONAL_MODULES = [ "path/to/module.yaml", "path/to/other_module.yaml" ]

These modules will then be launched by the runserver command automatically and be given sequential ports after the default module (e.g. 8000, 8001, 8002 etc.) 
