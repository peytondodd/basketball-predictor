import csv
import json
import re
import os
from bs4 import BeautifulSoup
from common import (calc_possessions,
                    include_team_rank,
                    make_request,
                    weighted_sos)
from constants import POWER_CONFERENCES, YEAR
from mascots import MASCOTS
from requests import Session


CONFERENCE_PAGE = 'https://www.sports-reference.com/cbb/seasons/%s.html'
RANKINGS_PAGE = 'https://www.sports-reference.com/cbb/seasons/%s-polls.html'
STATS_PAGE = 'http://www.sports-reference.com/cbb/seasons/%s-school-stats.html'
OPP_STATS_PAGE = 'http://www.sports-reference.com/cbb/seasons/%s-opponent-stats.html'
ADV_STATS_PAGE = 'http://www.sports-reference.com/cbb/seasons/%s-advanced-school-stats.html'
OPP_ADV_STATS_PAGE = 'https://www.sports-reference.com/cbb/seasons/%s-advanced-opponent-stats.html'
RATINGS_PAGE = 'http://www.sports-reference.com/cbb/seasons/%s-ratings.html'

# These stats are already included with the basic stats and should be skipped
FILTER_ADVANCED_STATS = ['g', 'wins', 'losses', 'win_loss_pct', 'srs', 'sos',
                         'wins_conf', 'losses_conf', 'wins_home', 'losses_home',
                         'wins_visitor', 'losses_visitor', 'pts', 'opp_pts',
                         'x']


def parse_name(href):
    name = href.replace('/cbb/schools/', '')
    name = re.sub('/.*', '', name)
    return name


def add_categories(stats):
    fg2 = stats['fg'] - stats['fg3']
    fg2a = stats['fga'] - stats['fg3a']
    fg2_pct = float(fg2 / fg2a)
    drb = stats['trb'] - stats['orb']
    stats['fg2'] = fg2
    stats['fg2a'] = fg2a
    stats['fg2_pct'] = fg2_pct
    stats['drb'] = drb
    return stats


def include_pace(stats):
    poss = calc_possessions(stats['fga'],
                            stats['fta'],
                            stats['orb'],
                            stats['tov'],
                            stats['opp_fga'],
                            stats['opp_fta'],
                            stats['opp_orb'],
                            stats['opp_tov'])
    # The 'mp' (minutes played) metric for teams is the total amount of minutes
    # the team has played, as opposed to the expected total amount of minutes
    # all players has played. For example, in a regular game, the TEAM plays for
    # 40 minutes while the PLAYERS play for a total of 200 minutes (40 minutes *
    # 5 players on the court at a time). Multiplying this number by 5 will give
    # the expected number of minutes for the pace calculation.
    pace = 40 * (poss / (0.2 * stats['mp'] * 5))
    stats['pace'] = pace
    return stats


def parse_advanced_stats(stats_html):
    all_stats = {}

    for team in stats_html.find_all('tr', class_='')[1:]:
        name = None
        stats = {}
        for stat in team.find_all('td'):
            if str(dict(stat.attrs).get('data-stat')) == 'school_name':
                name = parse_name(str(stat.a['href']))
                continue
            field = str(dict(stat.attrs).get('data-stat'))
            if field in FILTER_ADVANCED_STATS:
                continue
            value = float(stat.get_text())
            stats[field] = value
        all_stats[name] = stats
    return all_stats


def parse_opp_stats(stats_page):
    all_stats = {}

    team_stats = stats_page.find_all('tr', class_='')[1:]
    for team in team_stats:
        name = None
        stats = {}
        for stat in team.find_all('td'):
            field = str(dict(stat.attrs).get('data-stat'))
            if field == 'school_name':
                name = parse_name(str(stat.a['href']))
            if not field.startswith('opp_') or field == 'opp_mp':
                continue
            value = float(stat.get_text())
            stats[field] = value
        all_stats[name] = stats
    return all_stats


def parse_stats_page(stats_page, advanced_stats, opp_stats_page,
                     opp_advanced_stats, rankings, conferences,
                     power_conf_teams, ratings):
    sos_list = []
    teams_list = []

    stats_html = BeautifulSoup(stats_page.text, 'lxml')
    opp_stats_html = BeautifulSoup(opp_stats_page.text, 'lxml')
    adv_stats_html = BeautifulSoup(advanced_stats.text, 'lxml')
    opp_adv_stats_html = BeautifulSoup(opp_advanced_stats.text, 'lxml')
    sos_tags = stats_html.find_all('td', attrs={'data-stat': 'sos'})
    sos_tags = [float(tag.get_text()) for tag in sos_tags]
    min_sos = min(sos_tags)
    max_sos = max(sos_tags)

    advanced = parse_advanced_stats(adv_stats_html)
    opp_stats = parse_opp_stats(opp_stats_html)

    # The first row just describes the stats. Skip it as it is irrelevant.
    team_stats = stats_html.find_all('tr', class_='')[1:]
    for team in team_stats:
        name = None
        sos = None
        stats = {}
        for stat in team.find_all('td'):
            if str(dict(stat.attrs).get('data-stat')) == 'school_name':
                nickname = parse_name(str(stat.a['href']))
                name = stat.get_text()
                continue
            if str(dict(stat.attrs).get('data-stat')) == 'sos':
                sos = stat.get_text()
            field = str(dict(stat.attrs).get('data-stat'))
            if field == 'x':
                continue
            if field == 'opp_pts':
                field = 'away_pts'
            value = float(stat.get_text())
            stats[field] = value
            if nickname in power_conf_teams:
                stats["power_conf"] = 1
            else:
                stats["power_conf"] = 0
        try:
            rank = rankings[nickname]
        except KeyError:
            rank = '-'
        # Combine the basic and advanced stats plus the ratings into
        # one dictionary
        temp = advanced[nickname].copy()
        temp.update(stats)
        temp.update(ratings[nickname])
        temp.update(opp_stats[nickname])
        stats = temp

        stats = add_categories(stats)
        stats = include_team_rank(stats, rank)
        stats = include_pace(stats)
        stats = weighted_sos(stats, float(sos), stats['win_loss_pct'], max_sos,
                             min_sos)
        write_team_stats_file(nickname, stats, name, rankings, conferences)
        teams_list.append([name, nickname])
        sos_list.append([str(nickname), str(sos)])
    write_teams_list(teams_list)
    return sos_list, max_sos, min_sos


def get_stats_page(session, page):
    stats_page = make_request(session, page % YEAR)
    return stats_page


def save_sos_list(sos_list, max_sos, min_sos):
    with open('sos.py', 'w') as sos_file:
        sos_file.write('SOS = {\n')
        for pair in sos_list:
            name, sos = pair
            sos_file.write('    "%s": %s,\n' % (name, sos))
        sos_file.write('}\n')
        sos_file.write('MIN_SOS = %s\n' % min_sos)
        sos_file.write('MAX_SOS = %s\n' % max_sos)


def save_conferences(conferences_dict):
    with open('conferences.py', 'w') as conf_file:
        conf_file.write('CONFERENCES = {\n')
        for conf_name, teams in conferences_dict.items():
            conf_file.write('    "%s": %s,\n' % (conf_name, teams))
        conf_file.write('}\n')


def write_team_stats_file(nickname, stats, name, rankings, conferences):
    header = stats.keys()

    with open('team-stats/%s' % nickname, 'w') as team_stats_file:
        dict_writer = csv.DictWriter(team_stats_file, header)
        dict_writer.writeheader()
        dict_writer.writerows([stats])
    with open('team-stats/%s.json' % nickname, 'w') as stats_json_file:
        stats["name"] = name
        try:
            stats["rank"] = rankings[nickname]
        except KeyError:
            stats["rank"] = "NR"
        for key, value in conferences.items():
            if nickname in value:
                stats["conference"] = key
                break
        stats["mascot"] = MASCOTS[nickname]
        json.dump(stats, stats_json_file)


def write_teams_list(teams_list):
    with open('teams.py', 'w') as teams_file:
        teams_file.write('TEAMS = {\n')
        for team in teams_list:
            name, nickname = team
            teams_file.write('    "%s": "%s",\n' % (name, nickname))
        teams_file.write('}\n')


def get_rankings(session):
    rankings_dict = {}

    rankings_page = make_request(session, RANKINGS_PAGE % YEAR)
    rankings_html = BeautifulSoup(rankings_page.text, 'lxml')
    body = rankings_html.tbody
    # Only parse the first 25 results as these are the most recent rankings.
    for row in body.find_all('tr')[:25]:
        rank = None
        nickname = None
        for stat in row.find_all('td'):
            if str(dict(stat.attrs).get('data-stat')) == 'school_name':
                nickname = parse_name(str(stat.a['href']))
            if str(dict(stat.attrs).get('data-stat')) == 'rank':
                rank = stat.get_text()
        rankings_dict[nickname] = int(rank)
    return rankings_dict


def get_ratings(session):
    ratings_page = make_request(session, RATINGS_PAGE % YEAR)
    ratings_html = BeautifulSoup(ratings_page.text, 'lxml')
    ratings = {}
    for row in ratings_html.body.find_all('tr'):
        if not row.find('td'):
            continue
        ortg = float(row.find('td', {'data-stat': 'off_rtg'}).get_text())
        drtg = float(row.find('td', {'data-stat': 'def_rtg'}).get_text())
        nrtg = float(row.find('td', {'data-stat': 'net_rtg'}).get_text())
        name = row.find('td', {'data-stat': 'school_name'}).a['href']
        name = parse_name(name)
        ratings[name] = {
            'off_rtg': ortg,
            'def_rtg': drtg,
            'net_rtg': nrtg
        }
    return ratings


def get_conference_teams(session, conference_uri):
    teams = []

    url = 'http://www.sports-reference.com%s' % conference_uri
    conference_page = make_request(session, url)
    conference_html = BeautifulSoup(conference_page.text, 'lxml')
    body = conference_html.tbody
    for row in body.find_all('tr'):
        for stat in row.find_all('td'):
            if str(dict(stat.attrs).get('data-stat')) == 'school_name':
                name = str(stat).replace('<a href="/cbb/schools/', '')
                name = re.sub('/.*', '', name)
                name = re.sub('.*>', '', name)
                teams.append(name)
    return teams


def get_conferences(session):
    conference_dict = {}
    power_conference_teams = []

    conference_page = make_request(session, CONFERENCE_PAGE % YEAR)
    conference_html = BeautifulSoup(conference_page.text, 'lxml')
    body = conference_html.tbody
    for row in body.find_all('tr'):
        for stat in row.find_all('td'):
            if str(dict(stat.attrs).get('data-stat')) == 'conf_name':
                conf_name = stat.get_text()
                conf_uri = stat.a['href']
                teams = get_conference_teams(session, conf_uri)
                conference_dict[conf_name] = teams
                if conf_name in POWER_CONFERENCES:
                    power_conference_teams.append(teams)
    # Flatten the power_conference_teams list of lists
    power_conference_teams = [x for y in power_conference_teams for x in y]
    return conference_dict, power_conference_teams


def main():
    session = Session()
    session.trust_env = False

    conferences, power_conf_teams = get_conferences(session)
    rankings = get_rankings(session)
    ratings = get_ratings(session)
    stats_page = get_stats_page(session, STATS_PAGE)
    opp_stats_page = get_stats_page(session, OPP_STATS_PAGE)
    advanced_stats = get_stats_page(session, ADV_STATS_PAGE)
    opp_advanced_stats = get_stats_page(session, OPP_ADV_STATS_PAGE)
    if not stats_page:
        print 'Error retrieving stats page'
        return None
    sos_list, max_sos, min_sos = parse_stats_page(stats_page, advanced_stats,
                                                  opp_stats_page,
                                                  opp_advanced_stats, rankings,
                                                  conferences, power_conf_teams,
                                                  ratings)
    save_sos_list(sos_list, max_sos, min_sos)
    save_conferences(conferences)


if __name__ == "__main__":
    if not os.path.exists('team-stats'):
        os.makedirs('team-stats')
    main()
