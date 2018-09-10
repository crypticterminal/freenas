# -*- coding: utf-8 -*-
# Generated by Django 1.10.8 on 2018-09-03 13:29
from __future__ import unicode_literals

import re
from django.db import migrations, models


RE_MTU = re.compile(r'(?P<before>.*)\bmtu (?P<mtu>\d+)\b(?P<after>.*)')


def move_laggmember_options(apps, schema_editor):

    Interfaces = apps.get_model('network', 'interfaces')
    LAGGInterfaceMembers = apps.get_model('network', 'LAGGInterfaceMembers')
    for laggmember in LAGGInterfaceMembers.objects.all():
        interface = Interfaces.objects.filter(int_interface=laggmember.lagg_physnic)
        options = ''
        if laggmember.lagg_deviceoptions != 'up':
            if laggmember.lagg_deviceoptions.startswith('up'):
                options = laggmember.lagg_deviceoptions.replace('up ', '')
            elif laggmember.lagg_deviceoptions.endswith('up'):
                options = laggmember.lagg_deviceoptions.replace(' up', '')
            else:
                options = laggmember.lagg_deviceoptions.replace(' up ', '')

        if interface.exists():
            interface = interface[0]
            interface.int_options = options
            interface.save()
        else:
            Interfaces.objects.create(
                int_interface=laggmember.lagg_physnic,
                int_name=f'member of {laggmember.lagg_interfacegroup.lagg_interface.int_interface}',
                int_options=options,
            )


def move_mtu_from_options(apps, schema_editor):
    Interfaces = apps.get_model('network', 'interfaces')
    LAGGInterface = apps.get_model('network', 'LAGGInterface')

    for i in Interfaces.objects.all():
        if not i.int_options:
            continue
        reg = RE_MTU.search(i.int_options)
        if not reg:
            continue
        i.int_mtu = int(reg.group('mtu'))
        i.int_options = re.sub(r'\s{2,}', r' ', f'{reg.group("before")}{reg.group("after")}')
        i.save()

    for lagg in LAGGInterface.objects.all():
        lowest_mtu = None
        for member in lagg.lagginterfacemembers_set.all():
            interface = Interfaces.objects.filter(int_interface=member.lagg_physnic)
            if not interface.exists():
                continue
            interface = interface[0]
            if interface.int_mtu:
                if not lowest_mtu or interface.int_mtu < lowest_mtu:
                    lowest_mtu = interface.int_mtu
                interface.int_mtu = None
                interface.save()
        if lowest_mtu:
            interface = lagg.lagg_interface
            interface.int_mtu = lowest_mtu
            interface.save()


class Migration(migrations.Migration):

    dependencies = [
        ('network', '0008_auto_20171121_1029'),
    ]

    operations = [
        migrations.RunPython(move_laggmember_options, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='lagginterfacemembers',
            name='lagg_deviceoptions',
        ),
        migrations.AddField(
            model_name='interfaces',
            name='int_mtu',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='MTU'),
        ),
        migrations.RunPython(move_mtu_from_options, reverse_code=migrations.RunPython.noop),
    ]
