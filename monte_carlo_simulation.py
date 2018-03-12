import argparse
import itertools
import numpy
import pandas as pd
import random
import re
import requests
from bs4 import BeautifulSoup
from conferences import CONFERENCES
from common import (differential_vector,
                    extract_stats_components,
                    find_name_from_nickname,
                    find_nickname_from_name,
                    make_request,
                    read_team_stats_file)
from constants import YEAR
from datetime import datetime
from predictor import Predictor
from requests import Session
from teams import TEAMS


AWAY = 1
HOME = 0
NUM_SIMS = 200
TEAM_NAME_REGEX = 'schools/.*?/%s.html' % YEAR
SCHEDULE = 'http://www.sports-reference.com/cbb/schools/%s/%s-schedule.html'
SCORES_PAGE = 'http://www.sports-reference.com/cbb/boxscores/index.cgi?month='


def convert_team_totals_to_averages(stats):
    fields_to_average = ['mp', 'fg', 'fga', 'fg2', 'fg2a', 'fg3', 'fg3a', 'ft',
                         'fta', 'orb', 'drb', 'trb', 'ast', 'stl', 'blk', 'tov',
                         'pf']
    num_games = stats['g']
    new_stats = stats.copy()

    for field in fields_to_average:
        new_value = float(stats[field]) / num_games
        new_stats.loc[:,field] = new_value
    return new_stats


def get_winner(game, prediction):
    return game[list(prediction).index(max(list(prediction)))]


def get_totals(games_list, predictions, team_wins, conference_wins):
    for i in range(0, len(games_list)):
        winner = get_winner(games_list[i], predictions[i])
        team_wins[winner] += 1
    for team, wins in conference_wins.items():
        team_wins[team] += wins
    return team_wins


def teams_list(conference):
    if not conference:
        teams = TEAMS.values()
    else:
        teams = CONFERENCES[conference]
    return teams


def predict_all_matches(predictor, stats_dict, conference, schedule,
                        conference_wins):
    fields_to_rename = {'win_loss_pct': 'win_pct',
                        'opp_win_loss_pct': 'opp_win_pct'}
    games_list = []
    prediction_stats = pd.DataFrame()
    match_stats = []
    team_wins = {}

    for team in teams_list(conference):
        team_wins[team] = 0

    for matchup in schedule:
        home, away = matchup
        home_stats = stats_dict[home]
        away_stats = stats_dict['%s_away' % away]
        match_stats.append(pd.concat([away_stats, home_stats], axis=1))
    prediction_stats = pd.concat(match_stats)
    match_vector = differential_vector(prediction_stats)
    match_vector.rename(columns=fields_to_rename, inplace=True)
    match_stats_simplified = predictor.simplify(match_vector)
    predictions = predictor.predict(match_stats_simplified, int)
    team_wins = get_totals(schedule, predictions, team_wins, conference_wins)
    return team_wins


def create_variance(stats_dict, stdev_dict):
    local_stats_dict = {}

    for team, stats in stats_dict.items():
        local_stats = {}
        for stat in stats:
            min_val = -1 * float(stdev_dict[stat])
            max_val = abs(min_val)
            variance = random.uniform(min_val, max_val)
            new_value = float(stats[stat]) + variance
            local_stats[stat] = new_value
        local_stats_dict[team] = pd.DataFrame([local_stats])
    return local_stats_dict


def initialize_standings_dict(conference):
    standings_dict = {}
    overall_standings_dict = {}
    teams = teams_list(conference)

    for team in teams:
        team = find_name_from_nickname(team)
        overall_standings_dict[team] = [0] * len(teams)
    return overall_standings_dict


def print_probabilities_ordered(probabilities):
    sorted_ranks = [(v,k) for k,v in probabilities.iteritems()]
    sorted_ranks.sort(reverse=True)
    for probability, team in sorted_ranks:
        print '%s: %s%%' % (team, probability * 100.0)


def print_simulation_results(standings_dict, num_sims):
    for i in range(len(standings_dict)):
        print '=' * 80
        print '  Place: %s' % (i+1)
        print '=' * 80
        probabilities = {}
        for team, standings in standings_dict.items():
            probability = float(standings[i]) / float(num_sims)
            probabilities[team] = probability
        print_probabilities_ordered(probabilities)


def add_points_total(points_dict, team_wins):
    for team, wins in team_wins.items():
        if team in points_dict:
            points_dict[team] += wins
        else:
            points_dict[team] = wins
    return points_dict


def predict_all_simulations(predictor, stats_dict, stdev_dict, conference,
                            num_sims, schedule, conference_wins):
    standings_dict = initialize_standings_dict(conference)
    points_dict = {}

    for iteration in range(num_sims):
        local_stats_dict = create_variance(stats_dict, stdev_dict)
        team_wins = predict_all_matches(predictor, local_stats_dict, conference,
                                        schedule, conference_wins)
        points_dict = add_points_total(points_dict, team_wins)
        rankings = print_rankings(team_wins)
        for rank in range(len(rankings)):
            for team in rankings[rank]:
                standings_dict[team][rank] = standings_dict[team][rank] + 1
    print_simulation_results(standings_dict, num_sims)
    return standings_dict, points_dict


def get_conference_wins(team_soup):
    for div in team_soup.find_all('div'):
        wins = re.findall('<strong>Conference:</strong> \d+', str(div))
        if len(wins) > 0:
            return re.sub('.* ', '', wins[0])


def get_remaining_schedule(conference):
    session = Session()
    session.trust_env = False
    # remaining_schedule is a list of lists with the inner list being
    # the home first, followed by the away team (ie. [home, away])
    remaining_schedule = []
    current_records = {}

    for team in teams_list(conference):
        schedule = make_request(session, SCHEDULE % (team, YEAR))
        if not schedule:
            continue
        team_soup = BeautifulSoup(schedule.text, 'lxml')
        conference_wins = get_conference_wins(team_soup)
        current_records[team] = int(conference_wins)
        games = team_soup.find_all('table', {'class': 'sortable stats_table'})
        for game in games[-1].tbody.find_all('tr'):
            # Skip games that have already been played
            if game.find('a') and 'boxscores' in str(game.a):
                continue
            # Skip non-conference games
            if conference not in str(game):
                continue
            opponent = re.findall('schools/.*?/%s.html' % YEAR, str(game))
            opponent = re.sub('schools/', '', opponent[0])
            opponent = re.sub('/.*', '', opponent)
            location = game.find('td', {'class': 'left',
                                        'data-stat': 'game_location'})
            if location.get_text() == '@':
                remaining_schedule.append([opponent, team])
            else:
                remaining_schedule.append([team, opponent])
    remaining_schedule.sort()
    # Return a list of non-duplicate matches
    schedule = list(s for s, _ in itertools.groupby(remaining_schedule))
    return schedule, current_records


def create_stats_dictionary(conference):
    stats_dict = {}
    stdev_dict = {}
    combined_stats = pd.DataFrame()

    for team in teams_list(conference):
        stats = read_team_stats_file('team-stats/%s' % team)
        home_stats = extract_stats_components(stats)
        away_stats = extract_stats_components(stats, away=True)
        stats_dict[team] = home_stats
        stats_dict['%s_away' % team] = away_stats
        combined_stats = combined_stats.append(home_stats)
        combined_stats = combined_stats.append(away_stats)
    for col in combined_stats:
        stdev_dict[col] = combined_stats[col].std()
    return stats_dict, stdev_dict


def print_rankings(team_wins):
    rankings = [[] for i in range(len(team_wins))]
    sorted_ranks = [(v,k) for k,v in team_wins.iteritems()]
    sorted_ranks.sort(reverse=True)
    rank = 1
    previous_wins = None
    for i in range(len(sorted_ranks)):
        wins, team = sorted_ranks[i]
        team = find_name_from_nickname(team)
        if previous_wins != wins:
            rank = i + 1
        print '%s. %s: %s (rank %s)' % (str(i+1).rjust(3), team, wins, rank)
        previous_wins = wins
        rankings[rank-1].append(team)
    return rankings


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--conference', help='Optionally specify a particular '
    'conference to analyze the power rankings for. For example, specify "Big '
    'Ten Conference" to get power rankings only comprising the Big Ten teams.',
    default=None)
    parser.add_argument('--num-sims', '-n', help='Optionally specify the '
    'number of simulations to run. Default value is %s simulations.' % NUM_SIMS,
    default=NUM_SIMS)
    parser.add_argument('--dataset', help='Specify which dataset to use. For '
    'testing purposes, use the "sample-data" directory. For production '
    'deployments, use "matches" with current data that was pulled.',
    default='matches')
    return parser.parse_args()


def start_simulations(predictor, conference, num_sims=NUM_SIMS):
    stats_dict, stdev_dict = create_stats_dictionary(conference)
    schedule, conference_wins = get_remaining_schedule(conference)
    team_wins, points_dict = predict_all_simulations(predictor, stats_dict,
                                                     stdev_dict, conference,
                                                     num_sims, schedule,
                                                     conference_wins)
    return team_wins, points_dict, num_sims


def main():
    args = parse_arguments()
    predictor = Predictor(args.dataset)
    start_simulations(predictor, args.conference, int(args.num_sims))


if __name__ == "__main__":
    main()
