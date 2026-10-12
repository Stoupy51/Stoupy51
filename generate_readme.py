""" Regenerate the project tables of README.md and the contribution calendar it shows, from the GitHub API and PyPI. """
# Imports
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import TypedDict
from urllib.parse import quote

# Constants
USER: str = "Stoupy51"
OWNERS: list[str] = [USER, "Paralya"]
""" Accounts whose repositories are listed as projects rather than as contributions. """
UNIVERSITY: set[str] = {
	"807-DevOps-TD1", "INFO0606-KusoGrue", "INFO0705-Analyse", "INFO0804", "INFO0808-Visualisation", "INFO0901_GenerativeAI",
	"INFO0907_Blockchain", "INFO0908_OpenData", "INFO0909_SMA", "INFO0911_ImageAnalysis", "INFO0912_DeepLearning",
	"JeFilmeLeMetierQuiMePlait", "L3InfoCrypto", "Licence-3-Info", "ProjetINFO0803", "QuizCulture", "SportSocialNetwork",
	"StageM1Info", "TER_M2",
}
README: Path = Path(__file__).with_name("README.md")
START: str = "<!-- projects:start -->"
END: str = "<!-- projects:end -->"
SHIELDS: str = "style=flat-square&label="
""" Query string of every table badge, unlabelled since the column header names the value. """
CONTRIBUTION_LEVELS: list[str] = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
""" Values of GitHub's ContributionLevel enum, from no contribution to the most. """

REPOSITORIES_QUERY: str = """
query($login: String!, $cursor: String) {
	user(login: $login) {
		items: repositories(first: 20, after: $cursor, privacy: PUBLIC, ownerAffiliations: OWNER, isFork: false) {
			pageInfo { hasNextPage endCursor }
			nodes {
				name nameWithOwner url description stargazerCount isArchived pushedAt
				primaryLanguage { name }
				releases { totalCount }
				readme: object(expression: "HEAD:README.md") { ... on Blob { text } }
			}
		}
	}
}
"""
PULL_REQUESTS_QUERY: str = """
query($login: String!, $cursor: String) {
	user(login: $login) {
		items: pullRequests(first: 100, after: $cursor, states: MERGED) {
			pageInfo { hasNextPage endCursor }
			nodes { repository { nameWithOwner url description stargazerCount owner { login } } }
		}
	}
}
"""
CALENDAR_QUERY: str = """
query($login: String!) {
	user(login: $login) {
		contributionsCollection {
			contributionCalendar { totalContributions weeks { contributionDays { date weekday contributionLevel } } }
		}
	}
}
"""


# Classes
class PageInfo(TypedDict):
	hasNextPage: bool
	endCursor: str | None

class Page[T](TypedDict):
	pageInfo: PageInfo
	nodes: list[T]

class Name(TypedDict):
	name: str

class TotalCount(TypedDict):
	totalCount: int

class Blob(TypedDict):
	text: str | None

class Repository(TypedDict):
	name: str
	nameWithOwner: str
	url: str
	description: str | None
	stargazerCount: int
	isArchived: bool
	pushedAt: str
	primaryLanguage: Name | None
	releases: TotalCount
	readme: Blob | None

class Login(TypedDict):
	login: str

class Upstream(TypedDict):
	nameWithOwner: str
	url: str
	description: str | None
	stargazerCount: int
	owner: Login

class PullRequest(TypedDict):
	repository: Upstream

class PyPIInfo(TypedDict):
	name: str
	home_page: str | None
	project_urls: dict[str, str] | None

class ContributionDay(TypedDict):
	date: str
	weekday: int
	contributionLevel: str

class Week(TypedDict):
	contributionDays: list[ContributionDay]

class Calendar(TypedDict):
	totalContributions: int
	weeks: list[Week]


class Category(StrEnum):
	""" README section of a repository, in the order the sections appear. """
	PYTHON = "🐍 Python packages"
	DATAPACK = "⛏️ Minecraft datapacks"
	OTHER = "🧰 Other projects"
	UNIVERSITY = "🎓 School and university"


@dataclass(frozen=True)
class Platform:
	name: str
	page: re.Pattern[str]
	""" Badge link to the project page in a README, capturing the page then the project slug. """
	downloads: str
	""" shields.io image of the download count, with a `{slug}` placeholder. """

	@staticmethod
	def json_badge(api: str, query: str, color: str) -> str:
		return f"https://img.shields.io/badge/dynamic/json?url={quote(api, safe='{}')}&query={quote(query)}&color={color}&{SHIELDS}"


PLATFORMS: list[Platform] = [
	Platform(
		name="Modrinth",
		page=re.compile(r"\)\]\((https://modrinth\.com/(?:datapack|mod|plugin|resourcepack|project)/([\w-]+))"),
		downloads=f"https://img.shields.io/modrinth/dt/{{slug}}?color=1b7f4e&{SHIELDS}",
	),
	Platform(
		name="Smithed",
		page=re.compile(r"\)\]\((https://smithed\.net/packs/([\w-]+))"),
		downloads=Platform.json_badge("https://api.smithed.dev/v2/packs/{slug}/meta", "$.stats.downloads.total", "224bbb"),
	),
	Platform(
		name="PMC",
		page=re.compile(r"\)\]\((https://www\.planetminecraft\.com/data-pack/([\w-]+))"),
		downloads=Platform.json_badge("https://www.planetminecraft.com/data-pack/{slug}/statsv2", "$.downloads", "3f7d0b"),
	),
]
""" Download sites of the datapacks, found by the first link to each in a README. """


@dataclass(frozen=True)
class Palette:
	path: Path
	text: str
	levels: list[str]
	""" Cell color of each contribution level, in the order of `CONTRIBUTION_LEVELS`. """

	def calendar_svg(self, calendar: Calendar) -> str:
		""" Contribution calendar laid out like the one of the GitHub profile page. """
		step, left, top = 13, 32, 58
		weeks = calendar["weeks"]
		width, height = left + len(weeks) * step, top + 7 * step + 28
		legend_x = width - 40 - 5 * step

		months = [
			f'<text x="{left + x * step}" y="{top - 8}">{first:%b}</text>'
			for x, week in enumerate(weeks)
			if (first := date.fromisoformat(week["contributionDays"][0]["date"])).day <= 7
		]
		weekdays = [f'<text x="0" y="{top + day * step + 9}">{name}</text>' for day, name in ((1, "Mon"), (3, "Wed"), (5, "Fri"))]
		cells = [
			f'<rect x="{left + x * step}" y="{top + day["weekday"] * step}" width="10" height="10" rx="2" '
			f'fill="{self.levels[CONTRIBUTION_LEVELS.index(day["contributionLevel"])]}"/>'
			for x, week in enumerate(weeks)
			for day in week["contributionDays"]
		]
		legend = [
			f'<text x="{legend_x - 4}" y="{height - 8}" text-anchor="end">Less</text>',
			*(
				f'<rect x="{legend_x + i * step}" y="{height - 17}" width="10" height="10" rx="2" fill="{color}"/>'
				for i, color in enumerate(self.levels)
			),
			f'<text x="{legend_x + 5 * step + 1}" y="{height - 8}">More</text>',
		]
		return "\n".join([
			f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
			f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif" font-size="12" fill="{self.text}">',
			f'<text y="24" font-size="22" font-weight="600">{calendar["totalContributions"]:,} contributions in the last year</text>',
			*months, *weekdays, *cells, *legend,
			"</svg>\n",
		])


PALETTES: list[Palette] = [
	Palette(
		path=README.with_name("profile") / "calendar.svg",
		text="#1f2328",
		levels=["#eff2f5", "#aceebb", "#4ac26b", "#2da44e", "#116329"],
	),
	Palette(
		path=README.with_name("profile") / "calendar-dark.svg",
		text="#f0f6fc",
		levels=["#151b23", "#033a16", "#196c2e", "#2ea043", "#56d364"],
	),
]
""" GitHub's light and dark calendar colors, each drawn to its own file for the README to pick by theme. """


@dataclass(frozen=True)
class Project:
	repo: Repository
	category: Category
	pypi: str | None
	pages: dict[str, re.Match[str]]
	""" Page of the project on each platform its README links to, by platform name. """

	@staticmethod
	def classify(repo: Repository) -> "Project":
		readme: str = (repo["readme"] or Blob(text=None))["text"] or ""
		pages = {platform.name: match for platform in PLATFORMS if (match := platform.page.search(readme))}
		language = language_of(repo)

		if repo["name"] in UNIVERSITY:
			return Project(repo, Category.UNIVERSITY, pypi=None, pages={})
		if language == "Python" and (pypi := pypi_name(repo)):
			return Project(repo, Category.PYTHON, pypi=pypi, pages={})
		if pages or language == "mcfunction" or re.search(r"data ?pack", repo["description"] or "", re.IGNORECASE):
			return Project(repo, Category.DATAPACK, pypi=None, pages=pages)
		return Project(repo, Category.OTHER, pypi=None, pages={})

	@property
	def is_minor(self) -> bool:
		return not self.repo["stargazerCount"] and not self.repo["releases"]["totalCount"]

	@property
	def name_cell(self) -> str:
		name = self.repo["name"] if self.repo["nameWithOwner"].startswith(f"{USER}/") else self.repo["nameWithOwner"]
		cell = link_cell(name, self.repo["url"], self.repo["description"])
		return f"{cell} <sub>archived</sub>" if self.repo["isArchived"] else cell

	def row(self) -> dict[str, str]:
		""" Table cells of the project, keyed by column header. """
		repo = self.repo
		slug = repo["nameWithOwner"]
		release = badge(f"https://img.shields.io/github/v/release/{slug}?{SHIELDS}", f"{repo['url']}/releases")
		release = release if repo["releases"]["totalCount"] else ""
		stars = badge(f"https://img.shields.io/github/stars/{slug}?{SHIELDS}", f"{repo['url']}/stargazers")
		last_commit = badge(f"https://img.shields.io/github/last-commit/{slug}?{SHIELDS}", f"{repo['url']}/commits")

		if self.pypi:
			return {
				"Project": self.name_cell,
				"PyPI": badge(f"https://img.shields.io/pypi/v/{self.pypi}?{SHIELDS}", f"https://pypi.org/project/{self.pypi}"),
				"Python": badge(f"https://img.shields.io/pypi/pyversions/{self.pypi}?{SHIELDS}", f"https://pypi.org/project/{self.pypi}"),
				"Monthly downloads": badge(
					f"https://static.pepy.tech/personalized-badge/{self.pypi}?period=monthly&units=ABBREVIATION&right_color=GREEN&left_text=%E2%A4%93",
					f"https://pepy.tech/projects/{self.pypi}",
				),
				"Stars": stars,
				"Last commit": last_commit,
			}
		if self.category == Category.DATAPACK:
			downloads = {
				platform.name: (
					badge(platform.downloads.format(slug=page[2]), page[1]) if (page := self.pages.get(platform.name)) else ""
				)
				for platform in PLATFORMS
			}
			return {"Project": self.name_cell, "Release": release, "Stars": stars, **downloads, "Last commit": last_commit}
		return {
			"Project": self.name_cell,
			"Language": language_of(repo),
			"Release": release,
			"Stars": stars,
			"Last commit": last_commit,
		}

	def minor_row(self) -> dict[str, str]:
		return {
			"Project": self.name_cell,
			"Category": self.category.value,
			"Language": language_of(self.repo),
			"Description": (self.repo["description"] or "").replace("|", "\\|"),
		}


# Functions
def main() -> None:
	repositories = [repo for owner in OWNERS for repo in fetch_nodes(REPOSITORIES_QUERY, owner, Repository)]
	ranked = sorted(repositories, key=lambda repo: (not repo["isArchived"], repo["stargazerCount"], repo["pushedAt"]), reverse=True)
	projects = [Project.classify(repo) for repo in ranked if repo["nameWithOwner"] != f"{USER}/{USER}"]
	tables = {
		**{
			str(category): [project.row() for project in projects if project.category == category and not project.is_minor]
			for category in Category
		},
		"🤝 Contributions": contribution_rows(fetch_nodes(PULL_REQUESTS_QUERY, USER, PullRequest)),
	}

	sections = [f"### {title}\n\n{markdown_table(rows)}" for title, rows in tables.items() if rows]
	if minor := [project for project in projects if project.is_minor]:
		sections.append(minor_details(minor))
	before, _, rest = README.read_text(encoding="utf-8").partition(START)
	README.write_text(f"{before}{START}\n\n{'\n\n'.join(sections)}\n\n{END}{rest.partition(END)[2]}", encoding="utf-8")
	write_calendars()


def minor_details(minor: list[Project]) -> str:
	""" Collapsed table of the projects without stars or releases, grouped by category. """
	rows = [project.minor_row() for project in sorted(minor, key=lambda project: [*Category].index(project.category))]
	summary = f"🗃️ Smaller things, without stars or releases ({len(rows)})"
	return f"<details>\n<summary>{summary}</summary>\n\n{markdown_table(rows)}\n\n</details>"


def write_calendars() -> None:
	with urllib.request.urlopen(graphql_request(CALENDAR_QUERY, {"login": USER})) as response:
		calendar: Calendar = json.load(response)["data"]["user"]["contributionsCollection"]["contributionCalendar"]
	for palette in PALETTES:
		palette.path.write_text(palette.calendar_svg(calendar), encoding="utf-8")


def fetch_nodes[T](query: str, login: str, node_type: type[T]) -> list[T]:
	""" Every node of the `items` connection of a GraphQL query, following its pages.

	Args:
		node_type: Shape the query selects for each node, only read by the type checker.
	"""
	nodes: list[T] = []
	cursor: str | None = None
	while True:
		with urllib.request.urlopen(graphql_request(query, {"login": login, "cursor": cursor})) as response:
			page: Page[T] = json.load(response)["data"]["user"]["items"]
		nodes += page["nodes"]
		if not page["pageInfo"]["hasNextPage"]:
			return nodes
		cursor = page["pageInfo"]["endCursor"]


def graphql_request(query: str, variables: dict[str, str | None]) -> urllib.request.Request:
	return urllib.request.Request(
		"https://api.github.com/graphql",
		data=json.dumps({"query": query, "variables": variables}).encode(),
		headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"},
	)


def pypi_name(repo: Repository) -> str | None:
	""" Name of the PyPI project whose metadata links back to the repository, None when there is none. """
	try:
		with urllib.request.urlopen(f"https://pypi.org/pypi/{repo['name']}/json") as response:
			info: PyPIInfo = json.load(response)["info"]
	except urllib.error.HTTPError as error:
		if error.code != 404:
			raise
		return None
	links = [*(info["project_urls"] or {}).values(), info["home_page"] or ""]
	return info["name"] if any(link.rstrip("/").lower() == repo["url"].lower() for link in links) else None


def contribution_rows(pull_requests: list[PullRequest]) -> list[dict[str, str]]:
	""" One row per repository of another account, the ones with the most merged pull requests first. """
	merged_into = [pr["repository"] for pr in pull_requests if pr["repository"]["owner"]["login"] not in OWNERS]
	upstreams = {repo["nameWithOwner"]: repo for repo in merged_into}
	merged = Counter(repo["nameWithOwner"] for repo in merged_into)
	return [
		{
			"Project": link_cell(name, upstreams[name]["url"], upstreams[name]["description"]),
			"Stars": badge(f"https://img.shields.io/github/stars/{name}?{SHIELDS}", f"{upstreams[name]['url']}/stargazers"),
			"Merged PRs": f"[{count}]({upstreams[name]['url']}/pulls?q=is%3Apr+is%3Amerged+author%3A{USER})",
		}
		for name, count in sorted(merged.items(), key=lambda item: (item[1], upstreams[item[0]]["stargazerCount"]), reverse=True)
	]


def language_of(repo: Repository) -> str:
	return repo["primaryLanguage"]["name"] if repo["primaryLanguage"] else ""


def link_cell(name: str, url: str, description: str | None) -> str:
	""" Markdown link whose hover text is the description. """
	title = f' "{description.replace('"', "'").replace("|", "\\|")}"' if description else ""
	return f"[{name}]({url}{title})"


def badge(image: str, link: str) -> str:
	return f"[![]({image})]({link})"


def markdown_table(rows: list[dict[str, str]]) -> str:
	lines = [list(rows[0]), [":--"] * len(rows[0]), *(list(row.values()) for row in rows)]
	return "\n".join(f"| {' | '.join(line)} |" for line in lines)


if __name__ == "__main__":
	main()

