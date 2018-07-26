import asyncio
import datetime
import logging
import sqlite3
import os
import discord

from beem import Steem
from beem.account import Account
from beem.comment import Comment
from beem.exceptions import AccountDoesNotExistsException
from beem.instance import set_shared_steem_instance
from beem.nodelist import NodeList
from beem.utils import construct_authorperm, reputation_to_score
from dateutil.parser import parse
from discord.ext.commands import Bot

logging.basicConfig(level=logging.INFO)

db = sqlite3.connect('SFR.db')
cursor = db.cursor()

nodes = NodeList().get_nodes()
stm = Steem(node=nodes)
set_shared_steem_instance(stm)

categories = ['bid bot abuse',
              'bid bot misuse',
              'collusive voting',
              'comment self-vote violation',
              'comment spam',
              'copy/paste',
              'death threats',
              'failure to tag nsfw',
              'identity theft',
              'manipulation',
              'phishing',
              'plagiarism',
              'post farming',
              'scam',
              'spam',
              'tag abuse',
              'tag misuse',
              'testing for rewards',
              'threat',
              'vote abuse',
              'vote farming']  # Because the categories are sorted alphabetically, comment spam will be found before spam is, causing everything to work out as intended.


##################################################
# Uncomment for the initial setup of the database
# cursor.execute('''CREATE TABLE steemflagrewards
# (flagger TEXT, comment TEXT, post TEXT, category TEXT, created TEXT, included BOOL, payout REAL)''')
# cursor.execute('CREATE TABLE flaggers (name TEXT)')
# cursor.execute('CREATE TABLE sdl (name TEXT, created TEXT, delegation BOOL)')
# db.commit()
##################################################


def check_cat(comment):
    """Returning the matching category of abuse"""
    if '@steemflagrewards' in comment.lower():
        for cat in categories:
            if cat in comment.lower():
                return cat
        return
    return


def get_wait_time(account):
    """Preventing unability to comment, because of STEEM_MIN_REPLY_INTERVAL. Only works for one 'queued' comment."""
    for i in account.history_reverse(only_ops='comment'):
        if i['author'] == account['name']:
            wait = datetime.datetime.utcnow() - parse(i['timestamp'])
            wait = wait.seconds
            if wait > 20:  # TODO: Change to 3 once HF20 is out
                return 0
            else:
                return 20 - wait  # TODO: Change to 3 once HF20 is out as well


def report():
    """Posting a report post with the flaggers set as beneficiaries."""
    cursor.execute('DELETE FROM flaggers;')
    cursor.execute(
        'INSERT INTO flaggers SELECT DISTINCT flagger FROM steemflagrewards WHERE included == 0 ORDER BY created ASC LIMIT 8;')
    sql = cursor.execute(
        'SELECT \'[Comment](https://steemit.com/\' || post || \'#\' || comment || \')\', \'@\' || flagger, \'$\' || ROUND(payout, 3), category FROM steemflagrewards WHERE included == 0 AND flagger IN flaggers;')
    db.commit()
    table = '|Link|Flagger|Removed Rewards|Category|\n|:----|:-------|:---------------:|:--------|'
    for q in sql.fetchall():
        table += '\n|{}|{}|{}|{}|'.format(q[0], q[1], q[2], q[3])
    body = '## This post triggers once we have approved flags from 8 distinct flaggers via the SteemFlagRewards Abuse ' \
           'Fighting Community on our [Discord](https://discord.gg/NXG3JrH) ' \
           '\n\nhttps://steemitimages.com/DQmTJj2SXdXcYLh3gtsziSEUXH6WP43UG6Ltoq9EZyWjQeb/frpaccount.jpg\n\n Flaggers ' \
           'have been designated as post beneficiaries. Our goal is to empower abuse fighting plankton and minnows ' \
           'and promote a Steem that is less-friendly to abuse. It is simple. Building abuse fighters equals less ' \
           'abuse. \n\n\n{}'.format(table)
    logging.info('Generated post body')
    benlist = []
    sql = cursor.execute(
        '''SELECT flagger, COUNT(*) * 100 * 10 / (SELECT COUNT(*) FROM steemflagrewards WHERE included == 0 AND 
        flagger IN flaggers) FROM steemflagrewards WHERE flagger in flaggers AND included == 0 GROUP BY flagger ORDER 
        BY flagger;''')
    # Exchange 100 in line 99 with the percentage of the post rewards you want the flaggers to receive
    for q in sql.fetchall():
        benlist.append({'account': q[0], 'weight': q[1]})
    rep = stm.post(
        'Steem Flag Rewards Report - 8 Flagger Post - {}'.format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
        body, 'steemflagrewards', tags=['steemflagrewards', 'abuse', 'steem', 'steemit', 'flag'], beneficiaries=benlist,
        parse_body=True, self_vote=False)
    cursor.execute('UPDATE steemflagrewards SET included = 1 WHERE flagger in flaggers;')
    db.commit()
    return construct_authorperm(rep)


def fill_embed(embed:discord.Embed, names:list, template:str):
    """
    Function to add the contents of a list to a discord embed keeping the message size limit in mind
    """
    value = ''
    for n in names:
        if len(value + template.format(n[0])) < 1024:
            value += template.format(n[0])
        else:
            embed.add_field(name='...', value=value)
            value = template.format(n[0])
    embed.add_field(name='...', value=value)


loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
bot = Bot(description='SteemFlagRewards Bot', command_prefix='?')


@bot.command()
async def updatenodes(ctx):
    """Updates the nodes using the built in function that is based on hourly run benchmarks. Thanks holger80 for that feature."""
    global stm
    NodeList().update_nodes(steem_instance=stm)
    await ctx.send('Updated nodes using @fullnodeupdate.')


@bot.command()
async def approve(ctx, link):
    """Checks post pody for @steemflagrewards mention and https://steemit.com/ and must be in the flag_comment_review
    channel id """
    global sfrdvote
    if ctx.message.channel.id != 419711548769042432:
        await ctx.send('Send commands in the right channel please.')
        return
    logging.info('Registered command for {} by {}'.format(link, ctx.message.author.name))
    comment_perm = link.split('@')[-1]
    flaggers_comment = Comment(comment_perm)
    flagger = Account(flaggers_comment['author'])
    sfr = Account('steemflagrewards')
    sfrsp = stm.vests_to_sp(sfr['vesting_shares'].amount + sfr['received_vesting_shares'].amount - sfr[
        'delegated_vesting_shares'].amount)
    cat = check_cat(flaggers_comment['body'])
    if cat is None:
        await ctx.send('No abuse category found.')
        return
    await ctx.send('Abuse category acknowledged as {}'.format(cat))
    flagged_post = Comment('{}/{}'.format(flaggers_comment['parent_author'], flaggers_comment['parent_permlink']))
    weight = 0
    for v in flagged_post['active_votes']:
        if int(v['rshares']) < 0 and v['voter'] == flagger['name']:
            await ctx.send('Downvote confirmed')
            sfrdvote = v
            vote_pct = stm.rshares_to_vote_pct(abs(int(v['rshares'])), steem_power=sfrsp,
                                               voting_power=sfr.get_voting_power() * 100)
            weight = round((vote_pct / 10000) * 100)
            if weight >= 83:
                weight = 100
            else:
                weight += 17  # Flagging ROI incentivation
    if sfr.get_vote(flaggers_comment):
        await ctx.send('Already voted on this!')
        return
    elif not weight:
        await ctx.send('Apparently, the post wasn\'t flagged!')
        return
    logging.info('Attempting to vote now.')
    flaggers_comment.upvote(weight=weight, voter='steemflagrewards')
    body = 'Steem Flag Rewards mention comment has been approved! Thank you for reporting this abuse, @{} categorized as {}. This post was submitted via our Discord Community channel. Check us out on the following link!\n[SFR Discord](https://discord.gg/aXmdXRs)'.format(
        flaggers_comment['author'], cat)
    await asyncio.sleep(get_wait_time(sfr))
    stm.post('', body, reply_identifier='{}/{}'.format(flaggers_comment['author'], flaggers_comment['permlink']),
             community='SFR', parse_body=True, author='steemflagrewards')
    await ctx.send('Upvoted and commented.')
    cursor.execute('INSERT INTO steemflagrewards VALUES (?, ?, ?, ?, ?, ?, ?)', (
        flagger['name'], flaggers_comment.authorperm, flagged_post.authorperm, cat, flaggers_comment['created'], False,
        stm.rshares_to_sbd(sfrdvote['rshares'])))
    db.commit()
    q = \
        cursor.execute(
            'SELECT COUNT(DISTINCT flagger) FROM steemflagrewards WHERE included == 0;').fetchone()[
            0]
    await ctx.send('Now at {} out of 9 needed flaggers for a report.'.format(q))
    if q > 8:
        await ctx.send('Hit flagger threshold. Posting report.')
        r = report()
        msg = 'Sucessfully posted a new report! Check it out! (And upvote it as well :P)\nhttps://steemit.com/{}'.format(
            r)
        await ctx.send(msg)
        postpromo = bot.get_channel(426612204717211648)
        await postpromo.send(msg)
        sfr.claim_reward_balance()
    sfr.refresh()
    if sfr.get_voting_power() < 75:
        await ctx.send(
            'Hey my mojo is getting low. I should take a break... HEY! Let\'s all take a break. Convince someone to '
            'share a hug. I\'ll be back.\n(To be precise that means that the VP of the @steemflagrewards account has '
            'gone below 75%.)\nCurrently my full vote is worth about {} STU.'.format(
                str(round(sfr.get_voting_value_SBD(), 3))))


@bot.command()
async def status(ctx):
    """Returns the current status of the SFR account."""
    logging.info('Registered status command')
    embed = discord.Embed(title='SFR Status', description='The current status of the SFR bot and account.',
                          color=discord.Color.blue())
    sfr = Account('steemflagrewards')
    embed.add_field(name='Bot', value='Up and running')
    embed.add_field(name='Flaggers', value='{}/9'.format(cursor.execute(
        'SELECT COUNT(DISTINCT flagger) FROM steemflagrewards WHERE included == 0;').fetchone()[0]))
    embed.add_field(name='Mentions', value=cursor.execute(
        'SELECT COUNT(comment) FROM steemflagrewards WHERE included == 0;').fetchone()[0])
    embed.add_field(name='Removed payouts in the last 7 days', value=round(cursor.execute(
        'SELECT SUM(payout) FROM steemflagrewards WHERE created > DATETIME(\'now\', \'-7 days\');').fetchone()[0], 3))
    embed.add_field(name='Steem Power', value=round(sfr.get_steem_power(), 3))
    embed.add_field(name='Voting Power', value=round(sfr.get_voting_power(), 2))
    embed.add_field(name='Vote Value', value=round(sfr.get_voting_value_SBD(), 3))
    embed.add_field(name='Reputation', value=round(reputation_to_score(sfr['reputation']), 3))
    post = sfr.get_blog()[0]
    embed.add_field(name='Latest Post',
                    value='[{}](https://steemit.com/@{}/{})'.format(post['title'], post['author'], post['permlink']))
    embed.add_field(name='Awesomeness', value='Over 9000')
    await ctx.send(embed=embed)


@bot.command()
async def sdl(ctx, cmd: str, *mode: str):
    """
    Manage the list of the steemit defence league accounts with this command. Use it with ?sdl and one of the following
    """
    logging.info(f'{ctx.author.name} send sdl command with {cmd} ... {mode}')
    permitted = [405584423950614529,  # Iamstan
                 272137261548568576,  # Leonis
                 222012811172249600,  # Flugschwein
                 398204160538836993,  # Naturicia
                 347739387712372747,  # Anthonyadavisii
                 102394130176446464   # TheMarkyMark
                 ]  # A list of users who are allowed to edit the list.
    if cmd == 'add':
        if ctx.author.id not in permitted:
            await ctx.send('You do not have permissions to edit the SDL list.')
            return
        if not mode:
            await ctx.send('Please provide at least one account name.')
            return
        for i in mode:
            try:
                acc = Account(i)
            except AccountDoesNotExistsException:
                await ctx.send(f'The account @{i} seems to not exist on the steem blockchain.')
                continue
            if cursor.execute('SELECT name FROM sdl WHERE name == ?', (acc.name,)).fetchall():
                await ctx.send(f'Account @{acc.name} already exists in the list.')
                continue
            if acc['received_vesting_shares'].amount > 0:
                delegation = True
            else:
                delegation = False
            cursor.execute('INSERT INTO sdl VALUES (?, ?, ?)', (acc.name, acc['created'], delegation,))
            await ctx.send(f'Added @{acc.name} to the list.')
        db.commit()
        if len(mode) > 1:
            await ctx.send(':white_check_mark:')
    elif cmd == 'remove':
        if ctx.author.id not in permitted:
            await ctx.send('You do not have permissions to edit the SDL list.')
            return
        if not mode:
            await ctx.send('Please provide at least one account name.')
            return
        for i in mode:
            if not cursor.execute('SELECT name FROM sdl WHERE name == ?', (i,)).fetchall():
                await ctx.send(f'Could not find an account with the name @{i} in the list.')
                continue
            cursor.execute('DELETE FROM sdl WHERE name == ?', (i,))
            await ctx.send(f'Removed @{i} from the list.')
        db.commit()
        if len(mode) > 1:
            await ctx.send(':white_check_mark:')
    elif cmd == 'list':
        if 'steemd' in mode:
            link = '[{0}](https://steemd.com/@{0})\n'
        elif 'steemit' in mode:
            link = '[{0}](https://steemit.com/@{0})\n'
        else:
            msg = '\n**Accounts with delegations**\n```\n'
            names = cursor.execute('SELECT * FROM sdl ORDER BY delegation DESC, name ASC;').fetchall()
            for n in names:
                if n[2] == 0 and '**Accounts without delegations**' not in msg:
                    msg += '```\n**Accounts without delegations**\n```\n'
                msg += f'{n[0]}\n'
            await ctx.send(msg + '```')
            return
        delegated = discord.Embed(title='SDL with delegation', description='A list of Steemit Defence League accounts with a delegation (potentially by @steem)', color=discord.Color.gold())
        undelegated = discord.Embed(title='SDL without delegation', description='A list of Steemit Defence League accounts without delegations', color=discord.Color.blurple())
        names = cursor.execute('SELECT name FROM sdl WHERE delegation == 1 ORDER BY name ASC;').fetchall()
        fill_embed(delegated, names, link)
        names = cursor.execute('SELECT name FROM sdl WHERE delegation == 0 ORDER BY name ASC;').fetchall()
        fill_embed(undelegated, names, link)
        if 'delegated' in mode:
            await ctx.send(embed=delegated)
        elif 'undelegated' in mode:
            await ctx.send(embed=undelegated)
        else:
            await ctx.send(embed=delegated)
            await ctx.send(embed=undelegated)
    elif cmd == 'update':
        for i in cursor.execute('SELECT name FROM sdl WHERE delegation == 1;').fetchall():
            acc = Account(i[0])
            if acc['received_vesting_shares'] == 0:
                cursor.execute('UPDATE sdl SET delegation = 0 WHERE name == ?', i)
                await ctx.send(f'@{i[0]} got his delegation removed. :tada:')
                continue
            await ctx.send(f'@{i[0]} still got his delegation :(')
        db.commit()
    elif cmd == 'file':
        filename = '{}.steemitdefenseleague.txt'.format(datetime.datetime.now().strftime('%Y%m%d'))
        with open(filename, 'w+') as f:
            accounts = cursor.execute('SELECT name FROM sdl ORDER BY name ASC;').fetchall()
            for i in accounts:
                f.write(i[0] + '\n')
        await ctx.send(file=discord.File(filename))
    else:
        await ctx.send('Unknown command.')


def main():
    stm.wallet.unlock(os.getenv('PASSPHRASE'))
    bot.run(os.getenv('TOKEN'))


if __name__ == '__main__':
    main()
