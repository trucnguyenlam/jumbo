import click
from click_shell.core import Shell
import ipaddress as ipadd
from prettytable import PrettyTable

from jumbo.core import clusters, machines as vm, services
from jumbo.utils import session as ss, exceptions as ex


@click.group(invoke_without_command=True)
@click.option('--cluster', '-c')
@click.pass_context
def jumbo(ctx, cluster):
    """
    Execute a Jumbo command.
    If no command is passed, start the Jumbo shell interactive mode.
    """

    # Create the shell
    sh = Shell(prompt=click.style('jumbo > ', fg='green'),
               intro=click.style('Jumbo shell v0.1',
                                 fg='cyan'))
    # Save the shell in the click context (to modify its prompt later on)
    ctx.meta['jumbo_shell'] = sh.shell
    # Register commands that can be used in the shell
    sh.add_command(create)
    sh.add_command(exit)
    sh.add_command(delete)
    sh.add_command(manage)
    sh.add_command(addvm)
    sh.add_command(rmvm)
    sh.add_command(listcl)
    sh.add_command(listvm)
    sh.add_command(repair)
    sh.add_command(addcomp)

    # If cluster exists, call manage command (saves the shell in session
    #  variable svars and adapts the shell prompt)
    if cluster:
        if not clusters.check_cluster(cluster):
            click.echo('This cluster does not exist.'
                       ' Use `create NAME` to create it.', err=True)
        else:
            ctx.invoke(manage, name=cluster)

    # Run the command, or the shell if no command is passed
    sh.invoke(ctx)


@jumbo.command()
@click.pass_context
def exit(ctx):
    """Reset current context.

    :param ctx: Click context
    """

    if ss.svars.get('cluster'):
        ss.svars['cluster'] = None
        ctx.meta['jumbo_shell'].prompt = click.style('jumbo > ', fg='green')
    else:
        click.echo('Use `quit` to quit the shell. Exit only removes context.')


# cluster commands

def set_context(ctx, name):
    ctx.meta['jumbo_shell'].prompt = click.style(
        'jumbo (%s) > ' % name, fg='green')


@jumbo.command()
@click.argument('name')
@click.pass_context
def create(ctx, name):
    """Create a new cluster.

    :param name: New cluster name
    """

    click.echo('Creating %s...' % name)
    try:
        clusters.create_cluster(name)
    except ex.CreationError as e:
        click.secho(e.message, fg='red', err=True)
    else:
        click.echo('Cluster `%s` created.' % name)
        set_context(ctx, name)


@jumbo.command()
@click.argument('name')
@click.pass_context
def manage(ctx, name):
    """Set a cluster to manage. Persist --cluster option.

    :param name: Cluster name
    """

    click.echo('Loading %s...' % name)

    try:
        clusters.load_cluster(name)
    except ex.LoadError as e:
        click.secho(e.message, fg='red', err=True)
        if e.type == 'NoConfFile':
            click.secho('Use "repair" to regenerate `jumbo_config`.')
    else:
        click.echo('Cluster `%s` loaded.' % name)
        set_context(ctx, name)


@jumbo.command()
@click.argument('name')
@click.option('--force', '-f', is_flag=True, help='Force deletion')
def delete(name, force):
    """Delete a cluster.

    :param name: Name of the cluster to delete
    """

    if not force:
        if not click.confirm(
                'Are you sure you want to delete the cluster %s' % name):
            return
    try:
        clusters.delete_cluster(name)
    except ex.LoadError as e:
        click.secho(e.message, fg='red', err=True)
    else:
        click.echo('Cluster `%s` deleted.' % name)


@jumbo.command()
def listcl():
    """List clusters managed by Jumbo.
    """

    try:
        cluster_table = PrettyTable(['Name', 'Number of VMs'])
        for cluster in clusters.list_clusters():
            cluster_table.add_row([cluster['cluster'],
                                   len(cluster['machines'])])
    except ex.LoadError as e:
        click.secho(e.message, fg='red', err=True)
        if e.type == 'NoConfFile':
            click.echo('Use "repair" to regenerate `jumbo_config`.')
    else:
        click.echo(cluster_table)


@jumbo.command()
@click.argument('name')
def repair(name):
    """Recreate `jumbo_config` if it doesn't exist.

    :param name: Cluster name
    """

    if clusters.repair_cluster(name):
        click.echo('Recreated `jumbo_config` from scratch '
                   'for cluster `%s`.' % name)
    else:
        click.echo('Nothing to repair in cluster `%s`.' % name)

# VM commands


def validate_ip(ctx, param, value):
    try:
        ipadd.ip_address(value)
    except ValueError:
        raise click.BadParameter('%s is not a valid IP address.' % value)

    return value


@jumbo.command()
@click.argument('name')
@click.option('--types', '-t', multiple=True, type=click.Choice([
    'master', 'sidemaster', 'edge', 'worker', 'ldap', 'other']),
    required=True, help='VM host type(s)')
@click.option('--ip', '-i',  callback=validate_ip, prompt='IP',
              help='VM IP address')
@click.option('--ram', '-r', type=int, prompt='RAM (MB)',
              help='RAM allocated to the VM in MB')
@click.option('--disk', '-d', type=int, prompt='Disk (MB)',
              help='Disk allocated to the VM in MB')
@click.option('--cpus', '-p', default=1,
              help='Number of CPUs allocated to the VM')
@click.option('--cluster', '-c',
              help='Cluster in which the VM will be created')
@click.pass_context
def addvm(ctx, name, types, ip, ram, disk, cpus, cluster):
    """
    Create a new VM in the cluster being managed.
    Another cluster can be specified with "--cluster".

    :param name: New VM name
    """

    switched = False

    if not cluster:
        cluster = ss.svars['cluster']

    try:
        switched = vm.add_machine(name, ip, ram, disk, types, cluster, cpus)
    except ex.LoadError as e:
        click.secho(e.message, fg='red', err=True)
        if e.type == 'NoConfFile':
            click.secho('Use "repair" to regenerate `jumbo_config`.')
    else:
        click.echo('Machine `{}` added to cluster `{}`.'.format(name, cluster))

        # TODO: Only echo if in shell mode
        if switched:
            click.echo('\nSwitched to cluster `%s`.' % cluster)
            set_context(ctx, cluster)


@jumbo.command()
@click.argument('name')
@click.pass_context
@click.option('--cluster', '-c', help='Cluster of the VM to be deleted')
def rmvm(ctx, name, cluster):
    """Removes a VM.

    :param name: VM name
    """

    switched = False
    if not cluster:
        cluster = ss.svars['cluster']

    try:
        switched = vm.remove_machine(cluster, name)
    except ex.LoadError as e:
        click.secho(e.message, fg='red', err=True)
        if e.type == 'NoConfFile':
            click.secho('Use "repair" to regenerate `jumbo_config`')
    else:
        click.echo('Machine `{}` removed of cluster `{}`.'
                   .format(name, cluster))

        # TODO: Only echo if in shell mode
        if switched:
            click.echo('\nSwitched to cluster `%s`.' % cluster)
            set_context(ctx, cluster)


@jumbo.command()
@click.option('--cluster', '-c', help='Cluster in which to list the VMs')
def listvm(cluster):
    """
    List VMs in the cluster being managed.
    Another cluster can be specified with "--cluster".
    """

    if not cluster:
        cluster = ss.svars['cluster']

    try:
        vm_table = PrettyTable(
            ['Name', 'Types', 'IP', 'RAM (MB)', 'Disk (MB)', 'CPUs'])

        for m in clusters.list_machines(cluster):
            vm_table.add_row([m['name'], ', '.join(m['types']), m['ip'],
                              m['ram'], m['disk'], m['cpus']])
    except ex.LoadError as e:
        click.secho(e.message, fg='red', err=True)
    else:
        click.echo(vm_table)


# services commands


@jumbo.command()
@click.argument('name')
@click.option('--machine', '-m', required=True)
@click.option('--cluster', '-c')
def addcomp(name, machine, cluster):
    if not cluster:
        cluster = ss.svars['cluster']

    try:
        services.add_component(name, machine, cluster)
    except (ex.CreationError, ex.LoadError) as e:
        click.secho(e.message, fg='red', err=True)
    else:
        click.echo('Component `{}` added to machine {}/{}'
                   .format(name, machine, cluster))