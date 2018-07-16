# Copyright 2010 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
######################################################################
import dateutil
import logging
import os
import re
import time

from dateutil import parser as dtparser

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.translation import ugettext_lazy as _

from OpenSSL import crypto

from freenasUI import choices
from freenasUI.freeadmin.models import DictField, EncryptedDictField, Model, UserField
from freenasUI.middleware.notifier import notifier
from freenasUI.support.utils import get_license
from licenselib.license import ContractType

log = logging.getLogger('system.models')


CA_TYPE_EXISTING = 0x00000001
CA_TYPE_INTERNAL = 0x00000002
CA_TYPE_INTERMEDIATE = 0x00000004
CERT_TYPE_EXISTING = 0x00000008
CERT_TYPE_INTERNAL = 0x00000010
CERT_TYPE_CSR = 0x00000020


def time_now():
    return int(time.time())


class Settings(Model):
    stg_guiprotocol = models.CharField(
        max_length=120,
        choices=choices.PROTOCOL_CHOICES,
        default="http",
        verbose_name=_("Protocol")
    )
    stg_guicertificate = models.ForeignKey(
        "Certificate",
        verbose_name=_("Certificate"),
        limit_choices_to={'cert_type__in': [CERT_TYPE_EXISTING, CERT_TYPE_INTERNAL]},
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    stg_guiaddress = models.CharField(
        max_length=120,
        blank=True,
        default='0.0.0.0',
        verbose_name=_("WebGUI IPv4 Address")
    )
    stg_guiv6address = models.CharField(
        max_length=120,
        blank=True,
        default='::',
        verbose_name=_("WebGUI IPv6 Address")
    )
    stg_guiport = models.IntegerField(
        verbose_name=_("WebGUI HTTP Port"),
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        default=80,
    )
    stg_guihttpsport = models.IntegerField(
        verbose_name=_("WebGUI HTTPS Port"),
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        default=443,
    )
    stg_guihttpsredirect = models.BooleanField(
        verbose_name=_('WebGUI HTTP -> HTTPS Redirect'),
        default=True,
        help_text=_(
            'Redirect HTTP (port 80) to HTTPS when only the HTTPS protocol is '
            'enabled'
        ),
    )
    stg_language = models.CharField(
        max_length=120,
        choices=settings.LANGUAGES,
        default="en",
        verbose_name=_("Language")
    )
    stg_kbdmap = models.CharField(
        max_length=120,
        choices=choices.KBDMAP_CHOICES(),
        verbose_name=_("Console Keyboard Map"),
        blank=True,
    )
    stg_timezone = models.CharField(
        max_length=120,
        choices=choices.TimeZoneChoices(),
        default="America/Los_Angeles",
        verbose_name=_("Timezone")
    )
    stg_sysloglevel = models.CharField(
        max_length=120,
        choices=choices.SYS_LOG_LEVEL,
        default="f_info",
        verbose_name=_("Syslog level"),
        help_text=_("Specifies which messages will be logged by "
                    "server. INFO and VERBOSE log transactions that "
                    "server performs on behalf of the client. "
                    "f_is_debug specify higher levels of debugging output. "
                    "The default is f_info."),
    )
    stg_syslogserver = models.CharField(
        default='',
        blank=True,
        max_length=120,
        verbose_name=_("Syslog server"),
        help_text=_("Specifies the server and port syslog messages "
                    "will be sent to.  The accepted format is hostname:port "
                    "or ip:port, if :port is not specified it will default to "
                    "port 514 (this field currently only takes IPv4 addresses)"),
    )
    stg_wizardshown = models.BooleanField(
        editable=False,
        default=False,
    )
    stg_pwenc_check = models.CharField(
        max_length=100,
        editable=False,
    )

    class Meta:
        verbose_name = _("General")


class NTPServer(Model):
    ntp_address = models.CharField(
        verbose_name=_("Address"),
        max_length=120,
    )
    ntp_burst = models.BooleanField(
        verbose_name=_("Burst"),
        default=False,
        help_text=_(
            "When the server is reachable, send a burst of eight "
            "packets instead of the usual one. This is designed to improve"
            " timekeeping quality with the server command and s addresses."
        ),
    )
    ntp_iburst = models.BooleanField(
        verbose_name=_("IBurst"),
        default=True,
        help_text=_(
            "When the server is unreachable, send a burst of eight"
            " packets instead of the usual one. This is designed to speed "
            "the initial synchronization acquisition with the server "
            "command and s addresses."
        ),
    )
    ntp_prefer = models.BooleanField(
        verbose_name=_("Prefer"),
        default=False,
        help_text=_(
            "Marks the server as preferred. All other things being"
            " equal, this host will be chosen for synchronization among a "
            "set of correctly operating hosts."
        ),
    )
    ntp_minpoll = models.IntegerField(
        verbose_name=_("Min. Poll"),
        default=6,
        validators=[MinValueValidator(4)],
        help_text=_(
            "The minimum poll interval for NTP messages, as a "
            "power of 2 in seconds. Defaults to 6 (64 s), but can be "
            "decreased to a lower limit of 4 (16 s)"
        ),
    )
    ntp_maxpoll = models.IntegerField(
        verbose_name=_("Max. Poll"),
        default=10,
        validators=[MaxValueValidator(17)],
        help_text=_(
            "The maximum poll interval for NTP messages, as a "
            "power of 2 in seconds. Defaults to 10 (1,024 s), but can be "
            "increased to an upper limit of 17 (36.4 h)"
        ),
    )

    def __str__(self):
        return self.ntp_address

    class Meta:
        verbose_name = _("NTP Server")
        verbose_name_plural = _("NTP Servers")
        ordering = ["ntp_address"]

    class FreeAdmin:
        icon_model = "NTPServerIcon"
        icon_object = "NTPServerIcon"
        icon_view = "ViewNTPServerIcon"
        icon_add = "AddNTPServerIcon"


class Advanced(Model):
    adv_consolemenu = models.BooleanField(
        verbose_name=_("Show Text Console without Password Prompt"),
        default=False,
    )
    adv_serialconsole = models.BooleanField(
        verbose_name=_("Use Serial Console"),
        default=False,
    )
    adv_serialport = models.CharField(
        max_length=120,
        default="0x2f8",
        help_text=_(
            "Set this to match your serial port address (0x3f8, 0x2f8, etc.)"
        ),
        verbose_name=_("Serial Port Address"),
        choices=choices.SERIAL_CHOICES(),
    )
    adv_serialspeed = models.CharField(
        max_length=120,
        choices=choices.SERIAL_SPEED,
        default="9600",
        help_text=_("Set this to match your serial port speed"),
        verbose_name=_("Serial Port Speed")
    )
    adv_powerdaemon = models.BooleanField(
        verbose_name=_("Enable powerd (Power Saving Daemon)"),
        default=False,
    )
    adv_swapondrive = models.IntegerField(
        validators=[MinValueValidator(0)],
        verbose_name=_(
            "Swap size on each drive in GiB, affects new disks "
            "only. Setting this to 0 disables swap creation completely "
            "(STRONGLY DISCOURAGED)."
        ),
        default=2,
    )
    adv_consolemsg = models.BooleanField(
        verbose_name=_("Show console messages in the footer"),
        default=True,
    )
    adv_traceback = models.BooleanField(
        verbose_name=_("Show tracebacks in case of fatal errors"),
        default=True,
    )
    adv_advancedmode = models.BooleanField(
        verbose_name=_("Show advanced fields by default"),
        default=False,
        help_text=_(
            "By default only essential fields are shown. Fields considered "
            "advanced can be displayed through the Advanced Mode button."
        ),
    )
    adv_autotune = models.BooleanField(
        verbose_name=_("Enable autotune"),
        default=False,
        help_text=_(
            "Attempt to automatically tune the network and ZFS system control "
            "variables based on memory available."
        ),
    )
    adv_debugkernel = models.BooleanField(
        verbose_name=_("Enable debug kernel"),
        default=False,
        help_text=_(
            "The kernel built with debug symbols will be booted instead."
        ),
    )
    adv_uploadcrash = models.BooleanField(
        verbose_name=_("Enable automatic upload of kernel crash dumps and daily telemetry"),
        default=True,
    )
    adv_anonstats = models.BooleanField(
        verbose_name=_("Enable report anonymous statistics"),
        default=True,
        editable=False,
    )
    adv_anonstats_token = models.TextField(
        blank=True,
        editable=False,
    )
    adv_motd = models.TextField(
        max_length=10240,
        verbose_name=_("MOTD banner"),
        default='Welcome',
        blank=True,
    )
    adv_boot_scrub = models.IntegerField(
        default=7,
        editable=False,
    )
    adv_periodic_notifyuser = UserField(
        default="root",
        verbose_name=_("Periodic Notification User"),
        help_text=_("If you wish periodic emails to be sent to a different email address than "
                    "the alert emails are set to (root) set an email address for a user and "
                    "select that user in the dropdown.")
    )
    adv_cpu_in_percentage = models.BooleanField(
        default=False,
        verbose_name=_("Report CPU usage in percentage"),
        help_text=_("collectd will report CPU usage in percentage instead of \"jiffies\" "
                    "if this is checked."),
    )
    adv_graphite = models.CharField(
        max_length=120,
        default="",
        blank=True,
        verbose_name=_("Remote Graphite Server Hostname"),
        help_text=_("A hostname or IP here will be used as the destination to send collectd "
                    "data to using the graphite plugin to collectd.")
    )
    adv_fqdn_syslog = models.BooleanField(
        verbose_name=_("Use FQDN for logging"),
        default=False,
    )
    adv_sed_user = models.CharField(
        max_length=120,
        choices=choices.SED_USER,
        default="user",
        help_text=_("User passed to camcontrol security -u "
                    "for unlocking SEDs"),
        verbose_name=_("ATA Security User")
    )
    adv_sed_passwd = models.CharField(
        max_length=120,
        blank=True,
        help_text=_("Global password to unlock SED disks."),
        verbose_name=_("SED Password"),
    )

    class Meta:
        verbose_name = _("Advanced")

    class FreeAdmin:
        deletable = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.adv_sed_passwd:
            try:
                self.adv_sed_passwd = notifier().pwenc_decrypt(self.adv_sed_passwd)
            except Exception:
                log.debug('Failed to decrypt SED password', exc_info=True)
                self.adv_sed_passwd = ''
        self._adv_sed_passwd_encrypted = False

    def save(self, *args, **kwargs):
        if self.adv_sed_passwd and not self._adv_sed_passwd_encrypted:
            self.adv_sed_passwd = notifier().pwenc_encrypt(self.adv_sed_passwd)
            self._adv_sed_passwd_encrypted = True
        return super().save(*args, **kwargs)


class Email(Model):
    em_fromemail = models.CharField(
        max_length=120,
        verbose_name=_("From email"),
        help_text=_(
            "An email address that the system will use for the "
            "sending address for mail it sends, eg: freenas@example.com"
        ),
        default='',
    )
    em_outgoingserver = models.CharField(
        max_length=120,
        verbose_name=_("Outgoing mail server"),
        help_text=_(
            "A hostname or ip that will accept our mail, for "
            "instance mail.example.org, or 192.168.1.1"
        ),
        blank=True,
    )
    em_port = models.IntegerField(
        default=25,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text=_(
            "An integer from 1 - 65535, generally will be 25, "
            "465, or 587"
        ),
        verbose_name=_("Port to connect to"),
    )
    em_security = models.CharField(
        max_length=120,
        choices=choices.SMTPAUTH_CHOICES,
        default="plain",
        help_text=_("encryption of the connection"),
        verbose_name=_("TLS/SSL")
    )
    em_smtp = models.BooleanField(
        verbose_name=_("Use SMTP Authentication"),
        default=False
    )
    em_user = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Username"),
        help_text=_("A username to authenticate to the remote server"),
    )
    em_pass = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Password"),
        help_text=_("A password to authenticate to the remote server"),
    )

    class Meta:
        verbose_name = _("Email")

    class FreeAdmin:
        deletable = False

    def __init__(self, *args, **kwargs):
        super(Email, self).__init__(*args, **kwargs)
        if self.em_pass:
            try:
                self.em_pass = notifier().pwenc_decrypt(self.em_pass)
            except:
                log.debug('Failed to decrypt email password', exc_info=True)
                self.em_pass = ''
        self._em_pass_encrypted = False

    def save(self, *args, **kwargs):
        if self.em_pass and not self._em_pass_encrypted:
            self.em_pass = notifier().pwenc_encrypt(self.em_pass)
            self._em_pass_encrypted = True
        return super(Email, self).save(*args, **kwargs)


class Tunable(Model):
    tun_var = models.CharField(
        max_length=128,
        unique=True,
        verbose_name=_("Variable"),
    )
    tun_value = models.CharField(
        max_length=512,
        verbose_name=_("Value"),
    )
    tun_type = models.CharField(
        verbose_name=_('Type'),
        max_length=20,
        choices=choices.TUNABLE_TYPES,
        default='loader',
    )
    tun_comment = models.CharField(
        max_length=100,
        verbose_name=_("Comment"),
        blank=True,
    )
    tun_enabled = models.BooleanField(
        default=True,
        verbose_name=_("Enabled"),
    )

    def __str__(self):
        return str(self.tun_var)

    class Meta:
        verbose_name = _("Tunable")
        verbose_name_plural = _("Tunables")
        ordering = ["tun_var"]

    class FreeAdmin:
        icon_model = "TunableIcon"
        icon_object = "TunableIcon"
        icon_add = "AddTunableIcon"
        icon_view = "ViewTunableIcon"


class Alert(Model):
    node = models.CharField(default='A', max_length=100)
    source = models.TextField()
    key = models.TextField()
    datetime = models.DateTimeField()
    level = models.IntegerField()
    title = models.TextField()
    args = DictField()
    dismissed = models.BooleanField()

    class Meta:
        unique_together = (
            ('node', 'source', 'key'),
        )


class AlertDefaultSettings(Model):
    settings = DictField(
        blank=True,
    )

    class Meta:
        verbose_name = _("Alerts")

    class FreeAdmin:
        deletable = False
        icon_model = "AlertServiceIcon"
        icon_object = "AlertServiceIcon"
        icon_view = "AlertServiceIcon"
        icon_add = "AlertServiceIcon"


class AlertService(Model):
    name = models.CharField(
        max_length=120,
        verbose_name=_("Name"),
        help_text=_("Name to identify this alert service"),
    )
    type = models.CharField(
        verbose_name=_("Type"),
        max_length=20,
        default='Mail',
    )
    attributes = DictField(
        blank=True,
        editable=False,
        verbose_name=_("Attributes"),
    )
    enabled = models.BooleanField(
        verbose_name=_("Enabled"),
        default=True,
    )
    settings = DictField(
        blank=True,
        verbose_name=_("Settings"),
    )

    class Meta:
        verbose_name = _("Alert Service")
        verbose_name_plural = _("Alert Services")
        ordering = ["type"]

    class FreeAdmin:
        icon_model = "AlertServiceIcon"
        icon_object = "AlertServiceIcon"
        icon_add = "AddAlertServiceIcon"
        icon_view = "ViewAlertServiceIcon"

        exclude_fields = (
            'attributes',
            'settings',
            'id',
        )

    def __str__(self):
        return self.name


class SystemDataset(Model):
    sys_pool = models.CharField(
        max_length=1024,
        blank=True,
        verbose_name=_("Pool"),
        choices=()
    )
    sys_syslog_usedataset = models.BooleanField(
        default=False,
        verbose_name=_("Syslog")
    )
    sys_rrd_usedataset = models.BooleanField(
        default=True,
        verbose_name=_("Reporting Database"),
        help_text=_(
            'Save the Round-Robin Database (RRD) used by system statistics '
            'collection daemon into the system dataset'
        )
    )
    sys_uuid = models.CharField(
        editable=False,
        max_length=32,
    )
    sys_uuid_b = models.CharField(
        editable=False,
        max_length=32,
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = _("System Dataset")

    class FreeAdmin:
        deletable = False
        icon_model = "SystemDatasetIcon"
        icon_object = "SystemDatasetIcon"
        icon_view = "SystemDatasetIcon"
        icon_add = "SystemDatasetIcon"


class Update(Model):
    upd_autocheck = models.BooleanField(
        verbose_name=_('Check Automatically For Updates'),
        default=True,
    )
    upd_train = models.CharField(
        max_length=50,
        blank=True,
    )

    class Meta:
        verbose_name = _('Update')

    def get_train(self):
        # FIXME: lazy import, why?
        from freenasOS import Configuration
        conf = Configuration.Configuration()
        conf.LoadTrainsConfig()
        trains = conf.AvailableTrains() or []
        if trains:
            trains = list(trains.keys())
        if not self.upd_train or self.upd_train not in trains:
            return conf.CurrentTrain()
        return self.upd_train

    def get_system_train(self):
        from freenasOS import Configuration
        conf = Configuration.Configuration()
        conf.LoadTrainsConfig()
        return conf.CurrentTrain()


class CertificateBase(Model):
    cert_root_path = "/etc/certificates"

    cert_type = models.IntegerField()
    cert_name = models.CharField(
        max_length=120,
        verbose_name=_("Identifier"),
        help_text=_('Internal identifier of the certificate. Only alphanumeric, "_" and "-" are allowed.'),
        unique=True,
    )
    cert_certificate = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Certificate"),
        help_text=_("Cut and paste the contents of your certificate here"),
    )
    cert_privatekey = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Private Key"),
        help_text=_("Cut and paste the contents of your private key here"),
    )
    cert_CSR = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Signing Request"),
        help_text=_("Cut and paste the contents of your CSR here"),
    )
    cert_key_length = models.IntegerField(
        blank=True,
        null=True,
        verbose_name=_("Key length"),
        default=2048,
    )
    cert_digest_algorithm = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Digest Algorithm"),
        default='SHA256',
    )
    cert_lifetime = models.IntegerField(
        blank=True,
        null=True,
        verbose_name=_("Lifetime"),
        default=3650,
    )
    cert_country = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Country"),
        help_text=_("Country Name (2 letter code)"),
    )
    cert_state = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("State"),
        help_text=_("State or Province Name (full name)"),
    )
    cert_city = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Locality"),
        help_text=_("Locality Name (eg, city)"),
    )
    cert_organization = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Organization"),
        help_text=_("Organization Name (eg, company)"),
    )
    cert_organizational_unit = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Organizational Unit"),
        help_text=_("Organizational unit of the entity"),
    )
    cert_email = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Email Address"),
        help_text=_("Email Address"),
    )
    cert_common = models.CharField(
        blank=True,
        null=True,
        max_length=120,
        verbose_name=_("Common Name"),
        help_text=_("Common Name (eg, FQDN of FreeNAS server or service)"),
    )
    cert_san = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Subject Alternate Names"),
        help_text=_("Multi-domain support. Enter additional space separated domains")
    )
    cert_serial = models.CharField(
        blank=True,
        null=True,
        max_length=48,
        verbose_name=_("Serial"),
        help_text=_("Serial for next certificate"),
    )
    cert_signedby = models.ForeignKey(
        "CertificateAuthority",
        blank=True,
        null=True,
        verbose_name=_("Signing Certificate Authority"),
        on_delete=models.CASCADE
    )
    cert_chain = models.BooleanField(
        default=False,
    )
    # TODO: Probably move these fields to the certificate model so that they don't get included in CA Model
    cert_acme = models.ForeignKey(
        'ACMERegistration',
        on_delete=models.CASCADE,
        blank=True,
        null=True
    )
    cert_acme_uri = models.URLField(
        null=True,
        blank=True
    )
    cert_domains_authenticators = EncryptedDictField(
        null=True,
        blank=True
    )
    cert_renew_days = models.IntegerField(
        default=10,
        verbose_name=_("Renew certificate day"),  # Should we change the name ?
        help_text=_('Number of days to renew certificate before expiring')
    )

    def get_certificate(self):
        certificate = None
        try:
            if self.cert_certificate:
                certificate = crypto.load_certificate(
                    crypto.FILETYPE_PEM,
                    self.cert_certificate
                )
        except:
            pass
        return certificate

    def get_fingerprint(self):
        cert = self.get_certificate()
        return cert.digest("sha1").decode()

    def get_certificate_chain(self):
        regex = re.compile(r"(-{5}BEGIN[\s\w]+-{5}[^-]+-{5}END[\s\w]+-{5})+", re.M | re.S)

        certificates = []
        try:
            matches = regex.findall(self.cert_certificate)
            for m in matches:
                certificate = crypto.load_certificate(crypto.FILETYPE_PEM, m)
                certificates.append(certificate)
        except:
            pass

        return certificates

    def get_privatekey(self):
        privatekey = None
        if self.cert_privatekey:
            privatekey = crypto.load_privatekey(
                crypto.FILETYPE_PEM,
                self.cert_privatekey
            )
        return privatekey

    def get_CSR(self):
        CSR = None
        if self.cert_CSR:
            CSR = crypto.load_certificate_request(
                crypto.FILETYPE_PEM,
                self.cert_CSR
            )
        return CSR

    def get_certificate_path(self):
        return "%s/%s.crt" % (self.cert_root_path, self.cert_name)

    def get_privatekey_path(self):
        return "%s/%s.key" % (self.cert_root_path, self.cert_name)

    def get_CSR_path(self):
        return "%s/%s.csr" % (self.cert_root_path, self.cert_name)

    def __load_certificate(self):
        if self.cert_certificate is not None and self.__certificate is None:
            self.__certificate = self.get_certificate()

    def __load_CSR(self):
        if self.cert_CSR is not None and self.__CSR is None:
            self.__CSR = self.get_CSR()

    def __load_thingy(self):
        if self.cert_type == CERT_TYPE_CSR:
            self.__load_CSR()
        else:
            self.__load_certificate()

    def __get_thingy(self):
        thingy = self.__certificate
        if self.cert_type == CERT_TYPE_CSR:
            thingy = self.__CSR

        return thingy

    def __init__(self, *args, **kwargs):
        super(CertificateBase, self).__init__(*args, **kwargs)

        self.__certificate = None
        self.__CSR = None
        self.__load_thingy()

        if not os.path.exists(self.cert_root_path):
            os.mkdir(self.cert_root_path, 0o755)

    def __str__(self):
        return self.cert_name

    @property
    def cert_certificate_path(self):
        return "%s/%s.crt" % (self.cert_root_path, self.cert_name)

    @property
    def cert_privatekey_path(self):
        return "%s/%s.key" % (self.cert_root_path, self.cert_name)

    @property
    def cert_CSR_path(self):
        return "%s/%s.csr" % (self.cert_root_path, self.cert_name)

    @property
    def cert_internal(self):
        internal = "YES"

        if self.cert_type == CA_TYPE_EXISTING:
            internal = "NO"
        elif self.cert_type == CERT_TYPE_EXISTING:
            internal = "NO"

        return internal

    @property
    def cert_issuer(self):
        issuer = None

        if self.cert_type in (CA_TYPE_EXISTING, CERT_TYPE_EXISTING):
            issuer = "external"
        elif self.cert_type == CA_TYPE_INTERNAL:
            issuer = "self-signed"
        elif self.cert_type in (CERT_TYPE_INTERNAL, CA_TYPE_INTERMEDIATE):
            issuer = self.cert_signedby
        elif self.cert_type == CERT_TYPE_CSR:
            issuer = "external - signature pending"

        return issuer

    @property
    def cert_ncertificates(self):
        count = 0
        certs = Certificate.objects.all()
        for cert in certs:
            try:
                if self.cert_name == cert.cert_signedby.cert_name:
                    count += 1
            except:
                pass
        return count

    @property
    def cert_DN(self):
        self.__load_thingy()

        parts = []
        for c in self.__get_thingy().get_subject().get_components():
            parts.append("%s=%s" % (c[0].decode(), c[1].decode('utf8')))
        DN = "/%s" % '/'.join(parts)
        return DN

    #
    # Returns ASN1 GeneralizedTime - Need to parse it...
    #
    @property
    def cert_from(self):
        self.__load_thingy()

        thingy = self.__get_thingy()
        try:
            before = thingy.get_notBefore()
            t1 = dtparser.parse(before)
            t2 = t1.astimezone(dateutil.tz.tzutc())
            before = t2.ctime()
        except Exception:
            before = None

        return before

    #
    # Returns ASN1 GeneralizedTime - Need to parse it...
    #
    @property
    def cert_until(self):
        self.__load_thingy()

        thingy = self.__get_thingy()
        try:
            after = thingy.get_notAfter()
            t1 = dtparser.parse(after)
            t2 = t1.astimezone(dateutil.tz.tzutc())
            after = t2.ctime()
        except Exception:
            after = None

        return after

    @property
    def cert_type_existing(self):
        ret = False
        if self.cert_type & CERT_TYPE_EXISTING:
            ret = True
        return ret

    @property
    def cert_type_internal(self):
        ret = False
        if self.cert_type & CERT_TYPE_INTERNAL:
            ret = True
        return ret

    @property
    def cert_type_CSR(self):
        ret = False
        if self.cert_type & CERT_TYPE_CSR:
            ret = True
        return ret

    @property
    def CA_type_existing(self):
        ret = False
        if self.cert_type & CA_TYPE_EXISTING:
            ret = True
        return ret

    @property
    def CA_type_internal(self):
        ret = False
        if self.cert_type & CA_TYPE_INTERNAL:
            ret = True
        return ret

    @property
    def CA_type_intermediate(self):
        ret = False
        if self.cert_type & CA_TYPE_INTERMEDIATE:
            ret = True
        return ret

    class Meta:
        abstract = True


class CertificateAuthority(CertificateBase):

    def __init__(self, *args, **kwargs):
        super(CertificateAuthority, self).__init__(*args, **kwargs)

        self.cert_root_path = "%s/CA" % self.cert_root_path
        if not os.path.exists(self.cert_root_path):
            os.mkdir(self.cert_root_path, 0o755)

    class Meta:
        verbose_name = _("CA")
        verbose_name_plural = _("CAs")


class Certificate(CertificateBase):

    class Meta:
        verbose_name = _("Certificate")
        verbose_name_plural = _("Certificates")


class CloudCredentials(Model):
    name = models.CharField(
        verbose_name=_('Account Name'),
        max_length=100,
    )
    provider = models.CharField(
        verbose_name=_('Provider'),
        max_length=50,
        choices=(),
    )
    attributes = EncryptedDictField()

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Cloud Credential")


class Backup(Model):
    bak_finished = models.BooleanField(
        default=False,
        verbose_name=_("Finished")
    )

    bak_failed = models.BooleanField(
        default=False,
        verbose_name=_("Failed")
    )

    bak_acknowledged = models.BooleanField(
        default=False,
        verbose_name=_("Acknowledged")
    )

    bak_worker_pid = models.IntegerField(
        verbose_name=_("Backup worker PID"),
        null=True
    )

    bak_started_at = models.DateTimeField(
        verbose_name=_("Started at")
    )

    bak_finished_at = models.DateTimeField(
        verbose_name=_("Finished at"),
        null=True
    )

    bak_destination = models.CharField(
        max_length=1024,
        blank=True,
        verbose_name=_("Destination")
    )

    bak_status = models.CharField(
        max_length=1024,
        blank=True,
        verbose_name=_("Status")
    )

    class FreeAdmin:
        deletable = False

    class Meta:
        verbose_name = _("System Backup")


class Support(Model):
    enabled = models.NullBooleanField(
        verbose_name=_("Enable automatic support alerts to iXsystems"),
        default=False,
        null=True,
    )
    name = models.CharField(
        verbose_name=_('Name of Primary Contact'),
        max_length=200,
        blank=True,
    )
    title = models.CharField(
        verbose_name=_('Title'),
        max_length=200,
        blank=True,
    )
    email = models.EmailField(
        verbose_name=_('E-mail'),
        max_length=200,
        blank=True,
    )
    phone = models.CharField(
        verbose_name=_('Phone'),
        max_length=200,
        blank=True,
    )
    secondary_name = models.CharField(
        verbose_name=_('Name of Secondary Contact'),
        max_length=200,
        blank=True,
    )
    secondary_title = models.CharField(
        verbose_name=_('Secondary Title'),
        max_length=200,
        blank=True,
    )
    secondary_email = models.EmailField(
        verbose_name=_('Secondary E-mail'),
        max_length=200,
        blank=True,
    )
    secondary_phone = models.CharField(
        verbose_name=_('Secondary Phone'),
        max_length=200,
        blank=True,
    )

    class Meta:
        verbose_name = _("Proactive Support")

    class FreeAdmin:
        deletable = False

    @classmethod
    def is_available(cls, support=None):
        """
        Checks whether the Proactive Support tab should be shown.
        It should only be for TrueNAS and Siver/Gold Customers.

        Returns:
            tuple(bool, Support instance)
        """
        if notifier().is_freenas():
            return False, support
        if support is None:
            try:
                support = cls.objects.order_by('-id')[0]
            except IndexError:
                support = cls.objects.create()

        license, error = get_license()
        if license is None:
            return False, support
        if license.contract_type in (
            ContractType.silver,
            ContractType.gold,
        ):
            return True, support
        return False, support

    def is_enabled(self):
        """
        Returns if the proactive support is enabled.
        This means if certain failures should be reported to iXsystems.
        Returns:
            bool
        """
        return self.is_available(support=self)[0] and self.enabled


class ACMERegistrationBody(Model):
    contact = models.EmailField(
        verbose_name='Contact Email'
    )
    status = models.CharField(
        verbose_name='Status',
        max_length=10
    )
    key = models.TextField(
        verbose_name='JWKRSAKey'
    )
    acme = models.ForeignKey(
        'ACMERegistration',
        on_delete=models.CASCADE,
    )


class ACMERegistration(Model):
    uri = models.URLField(
        verbose_name='URI'
    )
    directory = models.URLField(
        verbose_name='Directory URI',
        unique=True
    )
    tos = models.URLField(
        verbose_name='Terms of Service'
    )
    new_account_uri = models.URLField(
        verbose_name='New Account Uri'
    )
    new_nonce_uri = models.URLField(
        verbose_name='New Nonce Uri'
    )
    new_order_uri = models.URLField(
        verbose_name='New Order Uri'
    )
    revoke_cert_uri = models.URLField(
        verbose_name='Revoke Certificate Uri'
    )


class DNSAuthenticator(Model):
    authenticator = models.CharField(
        max_length=64,
        verbose_name=_('Authenticator')
    )
    name = models.CharField(
        max_length=64,
        unique=True,
        verbose_name=_('Name')
    )
    attributes = EncryptedDictField()

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("DNS Authenticator")


class Filesystem(Model):
    identifier = models.CharField(max_length=255, unique=True)


class KeyValue(Model):
    key = models.CharField(max_length=255, unique=True)
    value = models.TextField()
