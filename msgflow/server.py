from pprint import pprint
import config
from tornado import web, ioloop, gen
from sockjs.tornado import SockJSRouter, SockJSConnection
import redis
import tornadoredis.pubsub
import psycopg2
import momoko


class Router(SockJSRouter):
    def __init__(self,
                 connection,
                 prefix='',
                 user_settings=dict(),
                 io_loop=None,
                 application=None):
        self.application = application
        super(Router, self).__init__(connection, prefix, user_settings, io_loop)


class Connection(SockJSConnection):
    @property
    def application(self):
        return self.session.server.application

    def on_open(self, request):
        cookie = request.cookies.get('user')
        if cookie:
            self.user = self.application.authenticate(cookie.value)
        else:
            self.user = None


class Application(web.Application):
    def __init__(self):
        echo_router = Router(EchoConnection, '/sockjs', application=self)

        handlers = [
            (r'/', MainHandler),
            (r'/login', LoginHandler),
            (r'/register', RegisterHandler)
        ] + echo_router.urls

        settings = {
            'template_path': config.TEMPLATE_PATH,
            'static_path': config.STATIC_PATH,
            'debug': config.DEBUG,
            'cookie_secret': config.SECRET,
            'database': config.DATABASE_DSN
        }

        self.redis = redis.Redis()
        self.subscriber = tornadoredis.pubsub.SockJSSubscriber(tornadoredis.Client())

        self.db = momoko.Pool(
            dsn=settings['database'],
            size=1
        )

        web.Application.__init__(self, handlers, **settings)

    def authenticate(self, token):
        if token:
            secret, user = token.split('|')
            if secret == self.settings['cookie_secret']:
                return user

    def make_token(self, user):
        return self.settings['cookie_secret'] + '|' + user


class BaseHandler(web.RequestHandler):
    def get_current_user(self):
        return self.application.authenticate(self.get_cookie('user'))


class MainHandler(BaseHandler):
    def get(self):
        if not self.current_user:
            self.redirect('/login')
            return
        self.render('index.html')


class LoginHandler(BaseHandler):
    def get(self):
        self.render('login.html')

    def post(self):
        email = self.get_argument('email')
        password = self.get_argument('password')

        if name and password:
            try:
                user = self.application.db.execute(
                    "select * from users where email = %s and password = %s", 
                    (email, password)
                )
                yield user

                if user.result().rowcount != 0:
                    token = self.application.make_token(email)
                    self.set_cookie('user', token)
                    self.redirect('/')                

            except (psycopg2.Warning, psycopg2.Error) as error:
                self.write(str(error))
                return


class RegisterHandler(BaseHandler):
    def get(self):
        self.render('register.html')

    @gen.coroutine
    def post(self):
        name = self.get_argument('name')
        email = self.get_argument('email')
        password = self.get_argument('password')

        if name and email and password:
            try:
                user = self.application.db.execute(
                    "select * from users where email = %s", (email, )
                )
                yield user

                if user.result().rowcount == 0:
                    self.application.db.execute(
                        "insert into users (name, email, password)"
                        "values(%s, %s, %s)",
                        (name, email, password)
                    )
                else:
                    self.write('User with that email is already registered')
                    return

            except (psycopg2.Warning, psycopg2.Error) as error:
                self.write(str(error))
                return
        else:
            self.redirect('/register')
            return

        self.redirect('/login')


class EchoConnection(Connection):

    def on_open(self, request):
        Connection.on_open(self, request)
        self.application.subscriber.subscribe('test_channel', self)
        message = 'User joined: ' + self.user
        self.application.redis.publish('test_channel', message)

    def on_message(self, msg):
        message = self.user + ': ' + msg
        self.application.redis.publish('test_channel', message)
        print('User {} sent message: {}'.format(self.user, msg))

    def on_close(self):
        message = 'User left: ' + self.user
        self.application.redis.publish('test_channel', message)
        self.application.subscriber.unsubscribe('test_channel', self)


if __name__ == '__main__':
    app = Application()

    ioloop = ioloop.IOLoop.instance()

    # this is a one way to run ioloop in sync
    future = app.db.connect()
    ioloop.add_future(future, lambda f: ioloop.stop())
    ioloop.start()
    future.result()  # raises exception on connection error

    app.listen(3000)
    ioloop.start()