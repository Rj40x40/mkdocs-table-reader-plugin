import os
import re
import textwrap

from mkdocs.plugins import BasePlugin
from mkdocs.config import config_options
from mkdocs.exceptions import ConfigurationError

from mkdocs_table_reader_plugin.safe_eval import parse_argkwarg
from mkdocs_table_reader_plugin.readers import READERS
from mkdocs_table_reader_plugin.utils import cd


class TableReaderPlugin(BasePlugin):

    config_scheme = (
        ("base_path", config_options.Choice(['docs_dir','config_dir'], default="config_dir")),
        ("data_path", config_options.Type(str, default=".")),
        ("search_page_directory", config_options.Type(bool, default=True)),
    )

    def on_config(self, config, **kwargs):
        """
        See https://www.mkdocs.org/user-guide/plugins/#on_config.

        Args:
            config

        Returns:
            Config
        """
        plugins = [p for p in config.get("plugins")]

        for post_load_plugin in ["macros", "markdownextradata"]:
            if post_load_plugin in plugins:
                if plugins.index("table-reader") > plugins.index(post_load_plugin):
                    raise ConfigurationError(f"[table-reader]: Incompatible plugin order: Define 'table-reader' before '{post_load_plugin}' in your mkdocs.yml.")


    def on_page_markdown(self, markdown, page, config, files, **kwargs):
        """
        Replace jinja tag {{ read_csv() }} in markdown with markdown table.

        The page_markdown event is called after the page's markdown is loaded
        from file and can be used to alter the Markdown source text.
        The meta- data has been stripped off and is available as page.meta
        at this point.

        https://www.mkdocs.org/user-guide/plugins/#on_page_markdown

        Args:
            markdown (str): Markdown source text of page as string
            page: mkdocs.nav.Page instance
            config: global configuration object
            site_navigation: global navigation object

        Returns:
            str: Markdown source text of page as string
        """
        # Determine the mkdocs directory
        # We do this during the on_page_markdown() event because other plugins
        # might have changed the directory.
        if self.config.get("base_path") == "config_dir":
            mkdocs_dir = os.path.dirname(os.path.abspath(config["config_file_path"]))
        if self.config.get("base_path") == "docs_dir":
            mkdocs_dir = os.path.abspath(config["docs_dir"])
        
        # Define directories to search for tables
        search_directories = [self.config.get("data_path")]
        if self.config.get("search_page_directory"):
            search_directories.append(os.path.dirname(page.file.abs_src_path))

        for reader, function in READERS.items():
            
            # Regex pattern for tags like {{ read_csv(..) }}
            # match group 0: to extract any leading whitespace 
            # match group 1: to extract the arguments (positional and keywords)
            tag_pattern = re.compile(
                "( *)\{\{\s+%s\((.+)\)\s+\}\}" % reader, flags=re.IGNORECASE
            )
            matches = re.findall(tag_pattern, markdown)
            
            for result in matches:

                # Safely parse the arguments
                pd_args, pd_kwargs = parse_argkwarg(result[1])

                # Load the table
                with cd(mkdocs_dir):

                    for data_path in search_directories:
                        # Make sure the path is relative to "data_path"
                        if len(pd_args) > 0:
                            input_file_path = pd_args[0]
                            output_file_path = os.path.join(data_path, input_file_path)
                            pd_args[0] = output_file_path

                        if pd_kwargs.get("filepath_or_buffer"):
                            input_file_path = pd_kwargs["filepath_or_buffer"]
                            output_file_path = os.path.join(data_path, input_file_path)
                            pd_kwargs["filepath_or_buffer"] = output_file_path

                        if os.path.exists(os.path.join(mkdocs_dir, output_file_path)):
                            # Found file
                            break
                    else:
                        # Could not find file in allowed dirs
                        raise FileNotFoundError(
                            f"[table-reader-plugin]: Cannot find table file '{input_file_path}'. The following directories were searched: {*search_directories,}"
                        )

                    markdown_table = function(*pd_args, **pd_kwargs)

                # Deal with indentation
                # f.e. relevant when used inside content tabs
                leading_spaces = result[0]
                # make sure it's in multiples of 4 spaces
                leading_spaces = int(len(leading_spaces) / 4) * "    "
                # indent entire table
                fixed_lines = []
                for line in markdown_table.split('\n'):
                    fixed_lines.append(textwrap.indent(line, leading_spaces))
                
                markdown_table = "\n".join(fixed_lines)

                # Insert markdown table
                # By replacing first occurance of the regex pattern
                markdown = tag_pattern.sub(markdown_table, markdown, count=1)


        return markdown
