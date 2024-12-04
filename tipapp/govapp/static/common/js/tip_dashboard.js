var tip_dashboard = {
  dt: null,
  progressBar: null,
  progressContainer: null,
  var: {
    hasInit: false,
    page: 1,
    page_size: 10,
    route_path: "",
    search: "",
    thermal_files_url: "/api/thermal-files/",
    data: [],
    breadcrumb: [],
    root: "",
    location: "",
    isDownloading: false,
  },

  init: function () {
    const _ = tip_dashboard;
    const params = new URL(document.location.toString()).searchParams;
    const route_path = params.get("route_path") ?? "";
    _.progressContainer = $("#progress-container");
    _.progressBar = _.progressContainer.find("#progress-bar");

    _.var.hasInit = false;
    _.var.page = Number(params.get("page")) || 1;
    _.var.page_size = Number(params.get("page_size")) || 10;
    _.var.route_path = route_path;
    _.var.search = params.get("search") ?? "";

    _.var.root = $("#route_path").val();
    _.var.location = window.location.href.split("?")[0];
    _.var.breadcrumb = route_path.split("/");

    _.renderBreadcrumb();

    // tip_dashboard.get_pending_imports();
    _.dt = $("#tip_dashboard table").DataTable({
      serverSide: true,
      ajax: function (data, callback, settings) {
        const routePathFromBreadcrum = _.var.breadcrumb
          .filter((b, i) => i > 0)
          .join("/");

        if (!_.var.hasInit) {
          _.var.hasInit = true;
        } else {
          _.var.page = data && data.start ? data.start / data.length + 1 : 1;
          _.var.page_size = data?.length;
          _.var.route_path = routePathFromBreadcrum;
          _.var.search = data?.search?.value;
        }

        _.get_folder_data(
          {
            page: _.var.page,
            page_size: _.var.page_size,
            route_path: _.var.route_path,
            search: _.var.search,
            draw: data?.draw,
          },
          function (response) {
            const { count, results } = response;
            callback({
              data: results,
              recordsTotal: count,
              recordsFiltered: count,
            });
          },
          function (error) {
            console.error(error);
            alert("There was an error fetching the files");
          }
        );
      },
      headerCallback: function (thead, data, start, end, display) {
        $(thead).addClass("table-light");
      },
      drawCallback: function (settings) {
        $("#tip_dashboard table .btn-download").on("click", function (e) {
          const filePath = $(this).data("path");
          const isDirectory = $(this).data("isDir") === true;
          tip_dashboard.downloadFile(
            filePath,
            isDirectory,
            (res, status, xhr) => {
              $("#tip_dashboard table button").attr("disabled", false);

              const blobObj = new Blob([res], {
                type: "application/x-7z-compressed",
              });
              const objectURL = URL.createObjectURL(blobObj);
              const a = document.createElement("a");
              a.href = objectURL;
              a.setAttribute(
                "download",
                `thermal_images_${new Date().toLocaleTimeString()}.7z`
              );
              a.click();
            },
            (error) => {
              console.log("Failed to download file");
              console.error(error);

              $("#tip_dashboard table button").attr("disabled", false);
            }
          );
        });
      },
      columns: [
        {
          title: "Name",
          data: "name",
          render: function (data, type, row) {
            if (!row.is_dir) return utils.markup("span", data);
            const path = row.path.replace(_.var.root, "");
            const href =
              tip_dashboard.var.location +
              "?" +
              utils.make_query_params({ route_path: path });

            return utils.markup(
              "a",
              [
                utils.markup("i", "", { class: "bi bi-folder " }),
                `&nbsp;${data}&nbsp;`,
              ],
              {
                href: href,
                class:
                  "btn-folder link-opacity-50-hovericon-link icon-link-hover",
                "data-folder": `${path}${row.name}`,
                style: "--bs-icon-link-transform: translate3d(0, -.125rem, 0);",
              }
            );
          },
        },
        {
          title: "Created at",
          data: "created_at",
        },

        {
          title: "Size",
          data: "size",
          render: function (data, type, row) {
            return utils.markup("span", utils.formatFileSize(data ?? 0));
          },
        },
        {
          title: "Download",
          data: "path",
          render: function (data, type, row) {
            return utils.markup(
              "button",
              { tag: "i", class: "bi bi-download" },
              {
                class: "btn-download btn btn-outline-dark border border-0",
                "data-path": row.path,
                "data-isDir": row.is_dir,
              }
            );
          },
        },
      ],
    });

    _.dt.state({
      start: (_.var.page - 1) * _.var.page_size,
      length: _.var.page_size,
      route_path: _.var.route_path,
    });
    _.dt.search(_.var.search);
  },

  renderBreadcrumb: function () {
    const breadcrumb = $("#dashboard-breadcrumb");
    breadcrumb.empty();
    const crumbs = tip_dashboard.var.breadcrumb ?? [];
    crumbs.unshift("");
    for (let i = 0; i < crumbs.length; i++) {
      const crumb = crumbs[i];
      const isActive = i === crumbs.length - 1;

      const href = isActive
        ? null
        : tip_dashboard.var.location +
          "?" +
          utils.make_query_params({
            route_path: crumbs.slice(1, i + 1).join("/"),
            page: 1,
            page_size: tip_dashboard.var.page_size,
          });

      const options = {
        class: ["breadcrumb-item", isActive ? "active" : ""].join(" "),
        "data-folder": crumbs.slice(0, i + 1).join("/"),
      };
      if (isActive) options["aria-current"] = "page";
      breadcrumb.append(
        utils.markup(
          "li",

          isActive ? crumb : utils.markup("a", crumb || "root", { href }),
          options
        )
      );
    }
  },

  handle_folder_click: function (e) {
    const folder = $(this).data("folder");
    const _ = tip_dashboard;
    _.var.breadcrumb = folder.split("/");
    _.dt.draw(true);
  },

  get_folder_data: function (params, cb_success, cb_error) {
    const _params = {
      page: params?.page ?? tip_dashboard.var.page,
      page_size: params?.page_size ?? tip_dashboard.var.page_size,
      route_path: params?.route_path ?? "",
      search: params?.search ?? "",
    };
    const queryParams = utils.make_query_params(_params);
    history.replaceState(null, null, "?" + queryParams.toString());

    $.ajax({
      url:
        tip_dashboard.var.thermal_files_url +
        "list_thermal_folder_contents/?" +
        queryParams,
      method: "GET",
      dataType: "json",
      contentType: "application/json",
      success: cb_success,
      error: cb_error,
    });
  },
  downloadFile: function (filePath, isDirectory, cb_success, cb_error) {
    const queryParams = utils.make_query_params({
      file_path: filePath,
    });

    $.ajax({
      url: tip_dashboard.var.thermal_files_url + "download/?" + queryParams,
      method: "GET",
      timeout: 15 * 60 * 1000, // sets timeout to 15 minutes

      xhrFields: { responseType: "blob" },
      success: cb_success,
      error: (e) => {
        downloadFinished(e);
        if (cb_error) cb_error(e);
      },
      xhr: function () {
        var xhr = new window.XMLHttpRequest();
        const _ = tip_dashboard;
        _.var.isDownloading = true;
        $("#tip_dashboard table button").attr("disabled", true);
        _.progressContainer.show();

        _.progressContainer
          .find("#filename")
          .text(isDirectory ? "Folder: " : "" + filePath.split("/").pop());

        xhr.addEventListener("progress", function handleEvent(e) {
          console.log(
            "Tranference: " + `${e.type}: ${e.loaded} bytes transferred\n`
          );
          const _ = tip_dashboard;
          if (e.lengthComputable) {
            var percentComplete = (e.loaded / e.total) * 100;
            _.progressBar.attr("aria-valuenow", percentComplete);
            _.progressBar.find(".progress-bar").width(percentComplete + "%");
            _.progressBar
              .find(".progress-bar")
              .text(percentComplete.toFixed(0) + "%");

            if (percentComplete === 100) {
              downloadFinished();
            }
          }
        });
        xhr.addEventListener("error", downloadError);
        xhr.addEventListener("abort", downloadError);
        return xhr;
      },
    });
  },
};

function downloadError(e) {
  const _ = tip_dashboard;
  const { markup } = utils;
  _.var.isDownloading = false;

  const errorAlert = markup(
    "div",
    [
      markup("button", "", {
        class: "btn-close",
        "data-bs-dismiss": "alert",
        "aria-label": "Close",
        type: "button",
      }),
      "There was an error downloading the file",
    ],
    { class: "alert alert-danger alert-dismissible fade show" }
  );
  $(errorAlert).insertAfter(_.progressContainer);
}
function downloadFinished(e) {
  const _ = tip_dashboard;
  _.var.isDownloading = false;

  setTimeout(function () {
    try {
      _.progressContainer.fadeOut("slow", function () {
        _.progressContainer.find("#filename").empty();
        _.progressBar.attr("aria-valuenow", 5);
        _.progressBar.find(".progress-bar").width("5%");
        _.progressBar.find(".progress-bar").text("5%");
      });
    } catch (error) {}
  }, 5000);
}
